import logging
from typing import Optional
from uuid import uuid4

from langgraph.graph import StateGraph, END

from src.database.postgresql import get_postgresql_db
from src.infrastructure.external.client.kakao_client import KakaoClient
from src.interfaces.validators.coord_validator import validate_seoul_polygon_contains
from src.interfaces.validators.highway_validator import validate_no_highway
from src.interfaces.validators.water_validator import snap_coordinate_from_water
from src.repository.user.user_repository import UserRepository
from src.repository.chat.chat_session_repository import ChatSessionRepository
from src.infrastructure.cache.repository.chat_state_repository import ChatStateRepository
from src.agent.nodes import (
    Extractor,
    WeightExtractor,
    Interviewer,
    RouteExecutor
)
from src.interfaces.schema.prewalk_schema import ChatResponse, ChatStatus
from src.schema.prewalk_schema import State, Location
from src.service.user.auth_service import AuthService
from src.agent.utils.chatbot_utils import PromptUtils
from src.config.logging import log_unexpected_error

logger = logging.getLogger(__name__)

# SSE 진행 알림용 문구.
# _build_graph()로 등록한 노드 이름과 동일해야 함.
NODE_PROGRESS_MESSAGE: dict[str, str] = {
    "extractor":         "정보를 추출하고 있습니다",
    "weight_extractor":  "선호도를 분석하고 있습니다",
    "interviewer":       "질문을 생성하고 있습니다",
    "route_executor":    "경로를 생성하고 있습니다",
}


class PrewalkOrchestrator:
    def __init__(
        self,
        kakao_client:            KakaoClient,
        auth_service:            AuthService,
        extractor:               Extractor,
        weight_extractor:        WeightExtractor,
        interviewer:             Interviewer,
        route_executor:          RouteExecutor
    ):
        self.kakao_client    = kakao_client
        self.auth_service    = auth_service
        self.graph           = self._build_graph(extractor, weight_extractor, interviewer, route_executor)

    def _build_graph(self, extractor, weight_extractor, interviewer, route_executor):
        """
        extractor, weight_extractor, interviewer, route_executor 노드를 연결합니다.
        """
        builder = StateGraph(State)

        # 모든 노드 정의
        builder.add_node("extractor",              extractor.run)
        builder.add_node("weight_extractor",        weight_extractor.run)
        builder.add_node("interviewer",             interviewer.run)
        builder.add_node("route_executor",          route_executor.run)

        # is_complete=True면 바로 route_executor로 들어가고
        # False면 extractor로 들어간다.
        builder.set_conditional_entry_point(
            lambda state: "route_executor" if state.is_complete else "extractor",
            {"route_executor": "route_executor", "extractor": "extractor"},
        )

        # extractor -> weight_extractor(가중치 라벨 추출, mode 확정 후 GPS Art/최단 스킵 판단) -> interviewer
        # -> 정보 부족O -> END(확인 대기 또는 재질문) -> 다음 턴에 다시 진입
        # -> 정보 부족X -> route_executor -> END
        builder.add_edge("extractor", "weight_extractor")
        builder.add_edge("weight_extractor", "interviewer")
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
        except Exception as exc:
            log_unexpected_error(logger, "prewalk_init_user_lookup_error", exc)
            return ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)

        try:
            thread_id = str(uuid4())
            ChatSessionRepository.save(user.id, thread_id)
        except Exception as exc:
            log_unexpected_error(logger, "prewalk_init_session_save_error", exc)
            return ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)

        # 초기 메시지
        init_message = "편안하고 안전한 길을 추천해드리는 ROUDI예요! 어떤 산책 코스를 추천해드릴까요? (예: 돌아오는 코스, 빠른 코스, 목적지까지 돌아가는 코스)"

        # 현재 위치 확인 — 실패 시 좌표만으로 Location 구성
        try:
            kakao_result = await self.kakao_client.get_address_from_coords(lat, lon)
            location = Location(
                lat        = lat,
                lon        = lon,
                address    = kakao_result.place_address,
                place_name = kakao_result.place_name,
            )
        except Exception as exc:
            log_unexpected_error(logger, "prewalk_init_kakao_error", exc)
            location = Location(lat=lat, lon=lon)

        initial_state = State(
            user_id          = user.id,
            current_location = location,
            response         = init_message,
        )

        try:
            await ChatStateRepository.save_state(thread_id=thread_id, state=initial_state)
        except Exception as exc:
            log_unexpected_error(logger, "prewalk_init_state_save_error", exc)

        return ChatResponse(status=status, thread_id=thread_id, state=initial_state)

    async def orchestrator(
        self,
        access_token: str,
        thread_id: str,
        user_prompt: str,
        lat: float,
        lon: float,
        confirmation: Optional[bool] = None,
    ):
        """
        Langgraph를 기반으로 정보 수집부터 경로 생성까지 진행합니다.
        진행 상황을 ("progress", 문구) 이벤트로,
        최종 결과를 ("result", ChatResponse) 이벤트로 yield하는 async generator입니다.
        """
        # 사용자 인증
        status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if status != ChatStatus.SUCCESS:
            yield "result", ChatResponse(status=status, thread_id=None, state=None)
            return

        # 챗봇 최근 대화 내역 조회
        try:
            state = await ChatStateRepository.get_state(thread_id)
        except Exception as exc:
            log_unexpected_error(logger, "prewalk_intent_state_load_error", exc)
            yield "result", ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)
            return

        if not state:
            yield "result", ChatResponse(status=ChatStatus.SESSION_NOT_FOUND, thread_id=None, state=None)
            return

        # 사용자의 접근 권한 확인
        try:
            user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
        except Exception as exc:
            log_unexpected_error(logger, "prewalk_intent_user_lookup_error", exc)
            yield "result", ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)
            return

        if state.user_id != user.id:
            yield "result", ChatResponse(status=ChatStatus.UNACCESSIBLE, thread_id=None, state=None)
            return

        # 최종 산책 조건에 대한 긍정/부정 여부 확인
        if state.awaiting_confirmation:
            state.awaiting_confirmation = False
            state.is_complete = bool(confirmation)
        else:
            state.is_complete = False

        # 현위치 갱신
        if not state.is_complete and (lat != state.current_location.lat or lon != state.current_location.lon):
            with get_postgresql_db() as db:
                validate_seoul_polygon_contains(lat, lon, db)
                snapped_lat, snapped_lon = snap_coordinate_from_water(lat, lon, db)
                if (snapped_lat, snapped_lon) == (lat, lon):
                    validate_no_highway(lat, lon, db)
                lat, lon = snapped_lat, snapped_lon

            try:
                kakao_result = await self.kakao_client.get_address_from_coords(lat, lon)
                state.current_location = Location(
                    lat        = lat,
                    lon        = lon,
                    address    = kakao_result.place_address,
                    place_name = kakao_result.place_name,
                )
            except Exception as exc:
                log_unexpected_error(logger, "prewalk_intent_kakao_error", exc)
                state.current_location = Location(lat=lat, lon=lon)

        state.access_token = access_token
        state.user_prompt  = PromptUtils.sanitize_user_prompt(user_prompt)  # 프롬프트 정규화

        # ainvoke 대신 astream(stream_mode="updates")을 써서 노드가 끝날 때마다
        # 진행 문구를 하나씩 내보낸다. 각 노드가 항상 전체 State를 반환하므로(부분
        # 필드가 아니라) update의 값이 곧 그 시점의 전체 State다 — 마지막으로 받은
        # 값이 그래프가 끝난 시점의 최종 State가 된다.
        try:
            async for update in self.graph.astream(state, stream_mode="updates"):
                for node_name, node_state in update.items():
                    if node_name in NODE_PROGRESS_MESSAGE:
                        yield "progress", NODE_PROGRESS_MESSAGE[node_name]
                    state = State.model_validate(node_state)
        except Exception as exc:
            log_unexpected_error(logger, "prewalk_intent_graph_error", exc)
            yield "result", ChatResponse(status=ChatStatus.INTERNAL_ERROR, thread_id=None, state=None)
            return

        final_state = state

        try:
            await ChatStateRepository.save_state(thread_id, final_state)
        except Exception as exc:
            log_unexpected_error(logger, "prewalk_intent_state_save_error", exc)

        yield "result", ChatResponse(
            status    = status,
            thread_id = thread_id,
            state     = final_state,
        )
