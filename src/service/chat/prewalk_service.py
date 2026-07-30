import logging
from uuid import uuid4

from langgraph.graph import StateGraph, END

from src.infrastructure.external.client.kakao_client import KakaoClient
from src.repository.user.user_repository import UserRepository
from src.repository.chat.chat_session_repository import ChatSessionRepository
from src.infrastructure.cache.repository.chat_state_repository import ChatStateRepository
from src.agent.nodes import (
    WeatherChecker,
    Extractor,
    Interviewer,
    ConfirmationClassifier,
    RouteExecutor
)
from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus
from src.schema.prewalk_schema import State, Location
from src.service.user.auth_service import AuthService

logger = logging.getLogger(__name__)


class PrewalkOrchestrator:
    def __init__(
        self,
        weather_checker:         WeatherChecker,
        kakao_client:            KakaoClient,
        auth_service:            AuthService,
        extractor:               Extractor,
        interviewer:             Interviewer,
        confirmation_classifier: ConfirmationClassifier,
        route_executor:          RouteExecutor
    ):
        self.weather_checker = weather_checker
        self.kakao_client    = kakao_client
        self.auth_service    = auth_service
        self.graph           = self._build_graph(extractor, interviewer, confirmation_classifier, route_executor)

    def _build_graph(self, extractor, interviewer, confirmation_classifier, route_executor):
        """
        extractor, interviewer, confirmation_classifier, route_executor 노드를 연결합니다.
        """
        builder = StateGraph(State)

        # 모든 노드 정의
        builder.add_node("extractor",              extractor.run)
        builder.add_node("interviewer",             interviewer.run)
        builder.add_node("confirmation_classifier", confirmation_classifier.run)
        builder.add_node("route_executor",          route_executor.run)

        # awaiting_confirmation=True -> confirmation_classifier(확인 응답 판정)
        # awaiting_confirmation=False -> extractor(새 정보 추출)
        builder.set_conditional_entry_point(
            lambda state: "confirmation_classifier" if state.awaiting_confirmation else "extractor",
            {"confirmation_classifier": "confirmation_classifier", "extractor": "extractor"},
        )

        # extractor -> interviewer -> 정보 부족O -> END(확인 대기 또는 재질문) -> 다음 턴에 다시 진입
        # extractor -> interviewer -> 정보 부족X -> route_executor -> END
        builder.add_edge("extractor", "interviewer")
        builder.add_conditional_edges(
            "interviewer",
            lambda state: "route_executor" if state.is_complete else END,
            {"route_executor": "route_executor", END: END},
        )

        # confirmation_classifier -> 긍정 -> route_executor
        # confirmation_classifier -> 부정 -> extractor(부정 응답에 섞인 수정 정보 반영 후 interviewer로)
        builder.add_conditional_edges(
            "confirmation_classifier",
            lambda state: "route_executor" if state.is_complete else "extractor",
            {"route_executor": "route_executor", "extractor": "extractor"},
        )

        builder.add_edge("route_executor", END)

        return builder.compile()

    async def get_init_message(self, access_token: str, lat: float, lon: float) -> ChatResponse:
        """
        대화 세션을 구축하고, 날씨 관련 환영 인사를 제공합니다.
        """
        # 사용자 확인
        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != ChatStatus.SUCCESS:
            return ChatResponse(status=status, thread_id=None, state=None)

        try:
            user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        except Exception:
            logger.exception("prewalk_init_user_lookup_error | provider=%s", provider)
            return ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)

        try:
            thread_id = str(uuid4())
            ChatSessionRepository.save(user.id, thread_id)
        except Exception:
            logger.exception("prewalk_init_session_save_error | user_id=%s", user.id)
            return ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)

        # 날씨 기반 초기 메시지
        init_message = await self.weather_checker.run(lat, lon)

        # 현재 위치 확인 — 실패 시 좌표만으로 Location 구성
        try:
            kakao_result = await self.kakao_client.get_address_from_coords(lat, lon)
            location = Location(
                lat        = lat,
                lon        = lon,
                address    = kakao_result.place_address,
                place_name = kakao_result.place_name,
            )
        except Exception:
            logger.exception("prewalk_init_kakao_error | lat=%s | lon=%s", lat, lon)
            location = Location(lat=lat, lon=lon)

        initial_state = State(
            user_id          = user.id,
            current_location = location,
            response         = init_message,
        )

        try:
            await ChatStateRepository.save_state(thread_id=thread_id, state=initial_state)
        except Exception:
            logger.exception("prewalk_init_state_save_error | thread_id=%s", thread_id)

        return ChatResponse(status=status, thread_id=thread_id, state=initial_state)

    async def orchestrator(self, access_token: str, thread_id: str, user_prompt: str) -> ChatResponse:
        """
        Langgraph를 기반으로 정보 수집부터 경로 생성까지 진행합니다.
        """
        # 사용자 인증
        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != ChatStatus.SUCCESS:
            return ChatResponse(status=status, thread_id=None, state=None)

        # 챗봇 최근 대화 내역 조회
        try:
            state = await ChatStateRepository.get_state(thread_id)
        except Exception:
            logger.exception("prewalk_intent_state_load_error | thread_id=%s", thread_id)
            return ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)

        if not state:
            return ChatResponse(status=ChatStatus.SESSION_NOT_FOUND, thread_id=None, state=None)

        # 사용자의 접근 권한 확인
        try:
            user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        except Exception:
            logger.exception("prewalk_intent_user_lookup_error | provider=%s", provider)
            return ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)

        if state.user_id != user.id:
            return ChatResponse(status=ChatStatus.UNACCESSIBLE, thread_id=None, state=None)

        state.access_token  = access_token
        state.user_prompt   = user_prompt
        state.route_result  = None

        # awaiting_confirmation 여부에 따라 confirmation_classifier/extractor 중 하나로 진입
        try:
            result      = await self.graph.ainvoke(state)
            final_state = State.model_validate(result)
        except Exception:
            logger.exception("prewalk_intent_graph_error | thread_id=%s", thread_id)
            return ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)

        try:
            await ChatStateRepository.save_state(thread_id, final_state)
        except Exception:
            logger.exception("prewalk_intent_state_save_error | thread_id=%s", thread_id)

        return ChatResponse(
            status    = status,
            thread_id = thread_id,
            state     = final_state,
        )
