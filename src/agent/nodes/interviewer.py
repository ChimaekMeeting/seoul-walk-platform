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
        self.place_tool   = PlaceTool()
        self.prompt_utils = PromptUtils()
        self.model        = self.llm.bind_tools(self.place_tool.tools)
        self.str_parser   = StrOutputParser()

    async def run(self, state: State) -> State:
        """
        정보가 부족하다면 -> 질문을 던지고
        정보가 충분하면   -> 경로 생성 시작을 알리는 메시지를 제공합니다.
        """
        is_complete  = self._is_complete(state.user_context)
        missing_info = self._get_missing_info(state.user_context)

        input_variables = {
            "current_context":  self.prompt_utils.format_for_prompt(state.user_context),
            "current_location": self.prompt_utils.format_for_prompt(state.current_location),
            "missing_info":     missing_info,
            "user_input":       state.user_prompt,
        }

        # 정보가 충분하다면 -> 경로 생성 시작을 알리는 메시지 제공
        if is_complete:
            response = await super().get_response(
                prompt_name     = "complete",
                input_variables = input_variables,
                parser          = self.str_parser,
            )
        # 정보가 부족하다면 -> 질문
        else:
            raw_response = await super().get_response(
                prompt_name="interview",
                input_variables=input_variables,
                llm=self.model,
            )

            candidates = await self._execute_tool_calls(
                raw_response.tool_calls if raw_response.tool_calls else [],
                state,
            )

            if candidates:
                if "origin_candidate" in candidates:
                    state.origin_candidate = candidates["origin_candidate"]
                    if state.user_context and candidates["origin_candidate"]:
                        state.user_context.origin = candidates["origin_candidate"][0]

                if "destination_candidate" in candidates:
                    state.destination_candidate = candidates["destination_candidate"]
                    if state.user_context and hasattr(state.user_context, "destination") and candidates["destination_candidate"]:
                        state.user_context.destination = candidates["destination_candidate"][0]

                is_complete = self._is_complete(state.user_context)

                if is_complete:
                    input_variables["current_context"] = self.prompt_utils.format_for_prompt(state.user_context)
                    response = await super().get_response(
                        prompt_name="complete",
                        input_variables=input_variables,
                        parser=self.str_parser,
                    )
                else:
                    response = await super().get_response(
                        prompt_name="location_formatter",
                        input_variables={
                            "tool_calls":       self.prompt_utils.format_for_prompt(candidates),
                            "user_input":       state.user_prompt,
                            "current_location": self.prompt_utils.format_for_prompt(state.current_location),
                        },
                        parser=self.str_parser,
                    )
            else:
                response = raw_response.content


        state.is_complete = is_complete
        state.response    = response
        
        print("[interviewer] pref:", state.user_context.model_dump_json(indent=2) if state.user_context else None)

        return state

    def _has_location(self, loc: Optional[Location]) -> bool:
        """
        위치 정보가 다 채워졌는지 점검합니다.
        """
        return (
            loc is not None
            and loc.lat        is not None
            and loc.lon        is not None
            and loc.address    is not None
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
        elif isinstance(pref, OnewayPreference):
            return self._has_location(pref.origin) and self._has_location(pref.destination) and pref.target_km is not None
        else:
            return self._has_location(pref.origin) and pref.target_km is not None

    def _get_missing_info(self, pref: Optional[BasePreference]) -> str:
        if pref is None:
            return "출발지, 목적지(편도인 경우), 목표 거리, 경로 유형"

        missing = []
        if pref.origin is None or pref.origin.place_name is None:
            missing.append("출발지 장소명")
        if isinstance(pref, (OnewayPreference, OnewayShortestPreference)):
            if pref.destination is None or pref.destination.place_name is None:
                missing.append("목적지 장소명")
        if isinstance(pref, (CircularPreference, OnewayPreference)):
            if pref.target_km is None:
                missing.append("목표 거리")

        return ", ".join(missing) if missing else ""


    async def _execute_tool_calls(self, tool_calls: list, state: State) -> dict:
        candidates = {}

        fallback_lat = (
            (state.user_context.origin.lat if state.user_context and state.user_context.origin else None)
            or state.current_location.lat
        )
        fallback_lon = (
            (state.user_context.origin.lon if state.user_context and state.user_context.origin else None)
            or state.current_location.lon
        )

        # 1. LLM이 요청한 tool calls 처리
        for call in tool_calls:
            name, args = call["name"], call["args"]
            target = args.get("target", "destination")

            if not args.get("lat") or not args.get("lon"):
                args["lat"] = fallback_lat
                args["lon"] = fallback_lon
            
            output = await self.place_tool.tool_map[name].ainvoke(args)

            print(f"[place_tool] keyword={args.get('query', name)}, target={target}, 결과수={len(output.documents) if isinstance(output, PlaceSearchResult) else 0}")
            
            if isinstance(output, PlaceSearchResult) and output.documents:
                for d in output.documents:
                    print(f"  - {d.place_name} ({d.address_name}) lat={d.y} lon={d.x}")
                candidates[f"{target}_candidate"] = [
                    Location(lat=float(d.y), lon=float(d.x), address=d.address_name, place_name=d.place_name)
                    for d in output.documents
                ]
                if target == "origin":
                    fallback_lat = float(output.documents[0].y)
                    fallback_lon = float(output.documents[0].x)

        # 2. place_name은 있지만 좌표가 없는 location 자동 보완
        if state.user_context:
            origin = state.user_context.origin
            # origin 자동 보완
            if origin and origin.place_name and origin.lat is None and "origin_candidate" not in candidates:
                result = await self.place_tool.get_address_from_keyword(
                    keyword=origin.place_name, lat=fallback_lat, lon=fallback_lon
                )
                print(f"[auto_resolve] origin 검색: '{origin.place_name}', 결과수={len(result.documents) if isinstance(result, PlaceSearchResult) else 0}")
                if isinstance(result, PlaceSearchResult) and result.documents:
                    for d in result.documents:
                        print(f"  - {d.place_name} ({d.address_name}) lat={d.y} lon={d.x}")
                    candidates["origin_candidate"] = [
                        Location(lat=float(d.y), lon=float(d.x), address=d.address_name, place_name=d.place_name)
                        for d in result.documents
                    ]
                    fallback_lat = float(result.documents[0].y)
                    fallback_lon = float(result.documents[0].x)

            # destination 자동 보완
            if hasattr(state.user_context, "destination"):
                dest = state.user_context.destination
                if dest and dest.place_name and dest.lat is None and "destination_candidate" not in candidates:
                    result = await self.place_tool.get_address_from_keyword(
                        keyword=dest.place_name, lat=fallback_lat, lon=fallback_lon
                    )
                    print(f"[auto_resolve] destination 검색: '{dest.place_name}', 결과수={len(result.documents) if isinstance(result, PlaceSearchResult) else 0}")
                    if isinstance(result, PlaceSearchResult) and result.documents:
                        for d in result.documents:
                            print(f"  - {d.place_name} ({d.address_name}) lat={d.y} lon={d.x}")
                        candidates["destination_candidate"] = [
                            Location(lat=float(d.y), lon=float(d.x), address=d.address_name, place_name=d.place_name)
                            for d in result.documents
                        ]

        return candidates

