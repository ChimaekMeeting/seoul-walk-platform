from langchain_core.output_parsers import StrOutputParser
from typing import Optional

from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.tools.place_tools import PlaceTool
from src.infrastructure.external.schema.place_schema import PlaceSearchResult
from src.agent.utils.chatbot_utils import PromptUtils
from src.schema.prewalk_schema import (
    State,
    Location,
    BasePreference,
    CircularPreference,
    OnewayPreference,
    OnewayShortestPreference,
)


class Interviewer(GPTClient):
    def __init__(self):
        super().__init__()
        self.place_tool = PlaceTool()
        self.prompt_utils = PromptUtils()
        self.model = self.llm.bind_tools(self.place_tool.tools)
        self.str_parser = StrOutputParser()

    async def run(self, state: State) -> State:
        """
        정보가 부족하다면 질문을 던지고, 충분하면 경로 생성 시작을 알립니다.
        """
        is_complete = self._is_complete(state.user_context)
        missing_info = self._get_missing_info(state.user_context)

        input_variables = {
            "current_context": self.prompt_utils.format_for_prompt(state.user_context),
            "current_location": self.prompt_utils.format_for_prompt(state.current_location),
            "missing_info": missing_info,
            "user_input": state.user_prompt,
        }

        if is_complete:
            response = await super().get_response(
                prompt_name="complete",
                input_variables=input_variables,
                parser=self.str_parser,
            )
        else:
            candidates = await self._lookup_unresolved_place_candidates(state)
            if candidates:
                if "origin_candidate" in candidates:
                    state.origin_candidate = candidates["origin_candidate"]
                if "destination_candidate" in candidates:
                    state.destination_candidate = candidates["destination_candidate"]

                response = await super().get_response(
                    prompt_name="location_formatter",
                    input_variables={
                        "tool_calls": self.prompt_utils.format_for_prompt(candidates),
                        "user_input": state.user_prompt,
                        "current_location": self.prompt_utils.format_for_prompt(state.current_location),
                        "target": self._resolve_candidate_target(candidates),
                    },
                    parser=self.str_parser,
                )
                state.is_complete = False
                state.response = response
                return state

            raw_response = await super().get_response(
                prompt_name="interview",
                input_variables=input_variables,
                llm=self.model,
            )

            if raw_response.tool_calls:
                candidates = await self._execute_tool_calls(raw_response.tool_calls)

                if "origin_candidate" in candidates:
                    state.origin_candidate = candidates["origin_candidate"]
                if "destination_candidate" in candidates:
                    state.destination_candidate = candidates["destination_candidate"]

                response = await super().get_response(
                    prompt_name="location_formatter",
                    input_variables={
                        "tool_calls": self.prompt_utils.format_for_prompt(candidates),
                        "user_input": state.user_prompt,
                        "current_location": self.prompt_utils.format_for_prompt(state.current_location),
                        "target": self._resolve_candidate_target(candidates),
                    },
                    parser=self.str_parser,
                )
            else:
                response = raw_response.content

        state.is_complete = is_complete
        state.response = response

        return state

    def _has_location(self, loc: Optional[Location]) -> bool:
        """
        위치 정보가 다 채워졌는지 점검합니다.
        """
        return (
            loc is not None
            and loc.lat is not None
            and loc.lon is not None
            and loc.address is not None
            and loc.place_name is not None
        )

    def _is_complete(self, pref: Optional[BasePreference]) -> bool:
        """
        경로 생성에 필요한 정보가 다 채워졌는지 확인합니다.
        """
        if pref is None:
            return False
        if isinstance(pref, OnewayShortestPreference):
            return self._has_location(pref.origin) and self._has_location(pref.destination)
        if isinstance(pref, OnewayPreference):
            return (
                self._has_location(pref.origin)
                and self._has_location(pref.destination)
                and pref.target_km is not None
            )
        return self._has_location(pref.origin) and pref.target_km is not None

    def _get_missing_info(self, pref: Optional[BasePreference]) -> str:
        """
        부족한 정보를 찾습니다.
        """
        if pref is None:
            return "출발지, 목적지(편도인 경우), 목표 거리, 경로 유형"

        missing = []
        if not self._has_location(pref.origin):
            missing.append("출발지 좌표")
        if isinstance(pref, (OnewayPreference, OnewayShortestPreference)):
            if not self._has_location(pref.destination):
                missing.append("목적지 좌표")
        if isinstance(pref, (CircularPreference, OnewayPreference)):
            if pref.target_km is None:
                missing.append("목표 거리")

        return ", ".join(missing) if missing else ""

    async def _lookup_unresolved_place_candidates(self, state: State) -> dict:
        """
        place_name만 있고 좌표가 없는 장소는 LLM 재질문 대신 후보 검색으로 넘깁니다.
        """
        pref = state.user_context
        if pref is None or not self._has_location(state.current_location):
            return {}

        targets = {}
        if self._needs_place_lookup(pref.origin):
            targets["origin"] = pref.origin.place_name
        if isinstance(pref, (OnewayPreference, OnewayShortestPreference)):
            if self._needs_place_lookup(pref.destination):
                targets["destination"] = pref.destination.place_name

        candidates = {}
        for target, keyword in targets.items():
            output = await self.place_tool.get_address_from_keyword(
                keyword=keyword,
                lat=state.current_location.lat,
                lon=state.current_location.lon,
                target=target,
            )
            if isinstance(output, PlaceSearchResult) and output.documents:
                candidates[f"{target}_candidate"] = [
                    Location(
                        lat=float(d.y),
                        lon=float(d.x),
                        address=d.address_name,
                        place_name=d.place_name,
                    )
                    for d in output.documents
                ]

        return candidates

    def _needs_place_lookup(self, loc: Optional[Location]) -> bool:
        """
        장소명은 있지만 좌표가 없으면 검색 후보 확인이 필요합니다.
        """
        return (
            loc is not None
            and loc.place_name is not None
            and (loc.lat is None or loc.lon is None)
        )

    def _resolve_candidate_target(self, candidates: dict) -> str:
        """
        장소 후보가 출발지용인지 목적지용인지 formatter 프롬프트에 전달합니다.
        """
        has_origin = "origin_candidate" in candidates
        has_destination = "destination_candidate" in candidates
        if has_origin and not has_destination:
            return "origin"
        if has_destination and not has_origin:
            return "destination"
        return ""

    async def _execute_tool_calls(self, tool_calls: list) -> dict:
        """
        place_tool을 통해 정확한 위치 데이터를 탐색합니다.
        """
        candidates = {}

        for call in tool_calls:
            name, args = call["name"], call["args"]
            target = args.get("target", "destination")
            output = await self.place_tool.tool_map[name].ainvoke(args)

            if isinstance(output, PlaceSearchResult) and output.documents:
                candidates[f"{target}_candidate"] = [
                    Location(
                        lat=float(d.y),
                        lon=float(d.x),
                        address=d.address_name,
                        place_name=d.place_name,
                    )
                    for d in output.documents
                ]

        return candidates
