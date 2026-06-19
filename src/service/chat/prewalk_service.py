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
from src.interfaces.schema.prewalk_schema import ChatResponse
from src.schema.prewalk_schema import State, Location


class PrewalkOrchestrator:
    def __init__(
        self,
        weather_checker: WeatherChecker,
        kakao_client:    KakaoClient,
        extractor:       Extractor,
        interviewer:     Interviewer,
        route_executor:  RouteExecutor,
    ):
        self.weather_checker = weather_checker
        self.kakao_client    = kakao_client
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

    async def get_init_message(self, user_uuid: str, lat: float, lon: float) -> ChatResponse:
        """
        대화 세션을 구축하고, 날씨 관련 환영 인사를 제공합니다.
        """
        user_id   = UserRepository.get_id_by_uuid(user_uuid)
        thread_id = str(uuid4())
        ChatSessionRepository.save(user_id, thread_id)

        env_info, init_message = await self.weather_checker.run(lat, lon)
        current_location = await self.kakao_client.get_address_from_coords(lat, lon)

        initial_state = State(
            user_uuid         = user_uuid,
            current_location  = Location(
                lat        = lat,
                lon        = lon,
                address    = current_location.place_address,
                place_name = current_location.place_name,
            ),
            weather_data = env_info,
            response     = init_message
        )

        await ChatStateRepository.save_state(thread_id=thread_id, state=initial_state)

        return ChatResponse(thread_id=thread_id, state=initial_state)

    async def orchestrator(self, thread_id: str, user_prompt: str) -> ChatResponse:
        """
        Langgraph를 기반으로 정보 수집부터 경로 생성까지 진행합니다.
        """
        state             = await ChatStateRepository.get_state(thread_id)
        state.user_prompt = user_prompt

        result      = await self.graph.ainvoke(state)
        final_state = State.model_validate(result)

        await ChatStateRepository.save_state(thread_id, final_state)

        return ChatResponse(
            thread_id = thread_id,
            state     = final_state,
        )
