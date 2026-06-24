from langchain_core.output_parsers import StrOutputParser

from src.schema.prewalk_schema import State
from src.interfaces.schema.walk_schema import WalkMode, Coordinate
from src.agent.tools.route_tools import RouteTool
from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils


MODE_TOOL_MAP: dict[WalkMode, str] = {
    WalkMode.CIRCULAR_RANDOM: "circular_random_route",
    WalkMode.ONEWAY_SHORTEST: "oneway_shortest_route",
    WalkMode.ONEWAY_RANDOM:   "oneway_random_route",
}


class RouteExecutor(GPTClient):
    def __init__(self):
        super().__init__()
        self.route_tool   = RouteTool()
        self.prompt_utils = PromptUtils()
        self.str_parser   = StrOutputParser()

    async def run(self, state: State) -> State:
        """
        경로를 생성하고, 결과를 자연어로 설명합니다.
        """
        tool_name = MODE_TOOL_MAP.get(state.mode)

        if not tool_name:
            return state

        args = {
            k: Coordinate(lat=v["lat"], lon=v["lon"]) if k in ("origin", "destination") else v
            for k, v in state.user_context.model_dump(exclude={"mode", "purpose"}, exclude_none=True).items()
        }
        
        args["access_token"] = state.access_token or ""
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
