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
    RouteExecutor
)
from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus
from src.schema.prewalk_schema import State, Location
from src.service.user.auth_service import AuthService

logger = logging.getLogger(__name__)


class PrewalkOrchestrator:
    def __init__(
        self,
        weather_checker: WeatherChecker,
        kakao_client:    KakaoClient,
        auth_service:    AuthService,
        extractor:       Extractor,
        interviewer:     Interviewer,
        route_executor:  RouteExecutor
    ):
        self.weather_checker = weather_checker
        self.kakao_client    = kakao_client
        self.auth_service    = auth_service
        self.graph           = self._build_graph(extractor, interviewer, route_executor)

    def _build_graph(self, extractor, interviewer, route_executor):
        """
        extractor, interviewer, route_executor 노드를 연결합니다.
        """
        builder = StateGraph(State)

        # 모든 노드 정의
        builder.add_node("extractor",      extractor.run)
        builder.add_node("interviewer",    interviewer.run)
        builder.add_node("route_executor", route_executor.run)

        # extractor -> interviewer -> 정보 부족O -> END -> extractor..
        # extractor -> interviewer -> 정보 부족X -> route_executor -> END
        builder.set_entry_point("extractor")
        builder.add_edge("extractor", "interviewer")
        builder.add_conditional_edges(
            "interviewer",
            lambda state: "route_executor" if state.is_complete else END,
            {"route_executor": "route_executor", END: END},
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

        # 날씨 확인 — 실패 시 기본 인사 메시지로 대체
        try:
            env_info, init_message = await self.weather_checker.run(lat, lon)
        except Exception:
            logger.exception("prewalk_init_weather_error | lat=%s | lon=%s", lat, lon)
            env_info     = None
            init_message = "안녕하세요! 오늘 어디로 산책을 떠나볼까요?"

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
            weather_data     = env_info,
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

        # 최근 프롬프트로 업데이트
        state.user_prompt  = user_prompt
        state.access_token = access_token

        # state 업데이트
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
