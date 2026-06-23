from typing import Union, Optional
from langchain_core.output_parsers import StrOutputParser
from src.schema.prewalk_schema import State
from src.interfaces.schema.walk_schema import CircularMode, OnewayMode, Coordinate
from src.agent.tools.route_tools import RouteTool
from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils
from src.schema.route_schema import Weights
from src.service.user.survey_service import TAG_WEIGHT_MAP
from src.repository.user.user_preference_repository import UserPreferenceRepository


MODE_TOOL_MAP: dict[Union[CircularMode, OnewayMode], str] = {
    CircularMode.RANDOM:  "circular_random_route",
    CircularMode.CHILD:   "circular_child_route",
    CircularMode.RUNNING: "circular_running_route",
    OnewayMode.SHORTEST:  "oneway_shortest_route",
    OnewayMode.RANDOM:    "oneway_random_route",
    OnewayMode.CHILD:     "oneway_child_route",
    OnewayMode.RUNNING:   "oneway_running_route",
}


class RouteExecutor(GPTClient):
    def __init__(self):
        super().__init__()
        self.route_tool   = RouteTool()
        self.prompt_utils = PromptUtils()
        self.str_parser   = StrOutputParser()

    async def run(self, state: State) -> State:
        """UserPreference와 테마 태그를 반영한 가중치로 경로를 생성합니다."""
        tool_name = MODE_TOOL_MAP.get(state.mode)
        if not tool_name:
            return state

        args = {
            k: Coordinate(lat=v["lat"], lon=v["lon"]) if k in ("origin", "destination") else v
            for k, v in state.user_context.model_dump(exclude={"mode", "purpose"}, exclude_none=True).items()
        }
        args["access_token"]   = state.access_token or ""
        args["custom_weights"] = self._build_weights(state)

        state.route_result = await self.route_tool.tool_map[tool_name].ainvoke(args)

        state.response = await super().get_response(
            prompt_name     = "route_result",
            input_variables = {
                "route_result":     self.prompt_utils.format_for_prompt(state.route_result),
                "user_context":     self.prompt_utils.format_for_prompt(state.user_context),
                "current_location": self.prompt_utils.format_for_prompt(state.current_location),
            },
            parser = self.str_parser,
        )
        return state

    def _build_weights(self, state: State) -> Weights:
        """
        UserPreference base weights에 state.themes의 delta를 합산해 최종 Weights를 반환합니다.
        UserPreference가 없으면 모든 가중치 기본값 0.5를 사용합니다.
        """
        preference = UserPreferenceRepository.get_by_user_id(state.user_id)

        base = {
            "safety":   (preference.weights_safety   if preference and preference.weights_safety   is not None else 0.5),
            "nature":   (preference.weights_nature   if preference and preference.weights_nature   is not None else 0.5),
            "slope":    (preference.weights_slope    if preference and preference.weights_slope    is not None else 0.5),
            "running":  (preference.weights_running  if preference and preference.weights_running  is not None else 0.5),
            "landmark": (preference.weights_landmark if preference and preference.weights_landmark is not None else 0.5),
            "child":    (preference.weights_child    if preference and preference.weights_child    is not None else 0.5),
        }

        for tag in state.themes:
            for key, delta in TAG_WEIGHT_MAP.get(tag, {}).items():
                base[key] = max(0.1, min(0.8, base[key] + delta * 0.5))

        weights = Weights(**base)
        print(f"[RouteExecutor] themes={state.themes}, weights={weights}")
        return weights
