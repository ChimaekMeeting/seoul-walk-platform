from typing import Union

from src.schema.prewalk_schema import State
from src.interfaces.schema.walk_schema import CircularMode, OnewayMode, Coordinate
from src.agent.tools.route_tools import RouteTool


MODE_TOOL_MAP: dict[Union[CircularMode, OnewayMode], str] = {
    CircularMode.RANDOM:  "circular_random_route",
    CircularMode.CHILD:   "circular_child_route",
    CircularMode.RUNNING: "circular_running_route",
    OnewayMode.SHORTEST:  "oneway_shortest_route",
    OnewayMode.RANDOM:    "oneway_random_route",
    OnewayMode.CHILD:     "oneway_child_route",
    OnewayMode.RUNNING:   "oneway_running_route",
}


class RouteExecutor:
    def __init__(self):
        self.route_tool = RouteTool()

    async def run(self, state: State) -> State:
        """
        경로를 생성합니다.
        """
        tool_name = MODE_TOOL_MAP.get(state.mode)

        # mode 관련 tool이 없는 경우
        if not tool_name:  return state

        args = {
            k: Coordinate(lat=v["lat"], lon=v["lon"]) if k in ("origin", "destination") else v
            for k, v in state.user_context.model_dump(
                exclude={
                    "mode",
                    "purpose",
                    "profile_name",
                    "child_friendly",
                    "unsupported_preferences",
                },
                exclude_none=True,
            ).items()
        }

        state.route_result = await self.route_tool.tool_map[tool_name].ainvoke(args)

        return state
