from langchain_core.output_parsers import StrOutputParser
from typing import Optional
import logging

from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.tools.place_tools import PlaceTool
from src.agent.tools.route_tools import RouteTool
from src.agent.nodes.route_executor import MODE_TOOL_MAP
from src.infrastructure.external.schema.place_schema import PlaceSearchResult
from src.agent.utils.chatbot_utils import PromptUtils
from src.config.logging import log_unexpected_error
from src.interfaces.errors import SAFE_INTERNAL_ERROR_DETAIL
from src.interfaces.validators.coord_validator import is_within_seoul_bbox
from src.interfaces.schema.walk_schema import Coordinate, PlaceLabel, WalkMode, WalkRouteStatus
from src.schema.prewalk_schema import (
    State,
    Location,
    BasePreference,
    CircularPreference,
    OnewayPreference,
    OnewayShortestPreference,
    GPSArtPreference,
    WayPointPreference,
)

logger = logging.getLogger(__name__)

class Interviewer(GPTClient):
    def __init__(self, route_service):
        super().__init__()
        # RouteExecutor.__init__과 같은 이유로 지연 임포트한다 — dependencies.py가
        # src.agent.nodes(Interviewer 포함)를 임포트하므로 모듈 최상단에서 곧장
        # dependencies를 임포트하면 순환 임포트가 된다.
        from src.interfaces.dependencies import get_gps_art_service
        self.place_tool    = PlaceTool()
        self.route_tool    = RouteTool(get_gps_art_service())  # oneway_shortest 최종 경로 생성용(타임아웃·스레드 오프로딩)
        self.prompt_utils  = PromptUtils()
        self.model         = self.llm.bind_tools(self.place_tool.tools)
        self.str_parser    = StrOutputParser()
        self.route_service = route_service

    async def run(self, state: State) -> State:
        """
        정보가 부족하다면 → 질문을 던지고
        정보가 충분하면   → 확인 메시지를 생성한다(경로는 사용자 확인 후 실행).
        모든 사용자 응대 문구는 interview.yaml을 통해 LLM이 생성한다.
        LLM/외부 API 호출이 실패하면 내부 원문 대신 공통 안전 메시지를 반환한다.
        """
        is_complete  = self._is_complete(state.user_context)
        missing_info = self._get_missing_info(state.user_context)
        await self._update_shortest_km(state)

        logger.info(f"is_complete: {is_complete}")
        logger.info(f"missing_info: {missing_info}")
        logger.info(f"shortest_km: {state.shortest_km}")

        # 정보가 충분해도, 편도 우회인데 목표 거리가 최단거리보다 짧거나 같으면
        # (우회할 여지가 없는 요청) 확인 질문 대신 이 사실부터 안내하고 어떻게 할지 되묻는다.
        if is_complete and self._is_oneway_shortest_conflict(state):
            state.is_complete = False
            state.response = await self._generate_response(
                state, missing_info="", shortest_km_conflict=state.shortest_km,
            )
            logger.info("interviewer_oneway_shortest_conflict | shortest_km=%s", state.shortest_km)
            return state

        # 정보가 충분하면 → 사용자 확인 질문 생성 (경로 실행은 확인 후)
        if is_complete:
            state.awaiting_confirmation = True
            state.is_complete           = False
            state.response = await self._generate_response(state, missing_info="")
            logger.info("interviewer_confirmation_pending")
            return state

        # 정보가 부족하면 → interview.yaml 호출 (장소 검색 tool 바인딩)
        try:
            raw_response = await super().get_response(
                prompt_name="interview",
                input_variables=self._build_input_variables(state, missing_info),
                llm=self.model,
            )
        except Exception as exc:
            log_unexpected_error(logger, "interviewer_interview_llm_error", exc)
            state.response = SAFE_INTERNAL_ERROR_DETAIL
            return state
        logger.info("interview.yaml이 호출되었습니다.")

        candidates, search_failures, out_of_seoul, api_error_message = await self._execute_tool_calls(
            raw_response.tool_calls if raw_response.tool_calls else [],
            state,
        )

        # Kakao API 호출 자체가 실패했으면 검색 결과 판단 없이 안전한 공통 문구를 보여준다.
        if api_error_message is not None:
            state.is_complete = False
            state.response    = api_error_message
            logger.info("Kakao API 호출 중 오류가 발생했습니다.")
            return state

        # 검색 결과가 0건이거나 전부 서울 밖인 대상이 있으면 LLM이 안내 문구를 생성한다.
        if search_failures or out_of_seoul:
            state.is_complete = False
            state.response = await self._generate_response(
                state, missing_info, search_failures=search_failures, out_of_seoul=out_of_seoul,
            )
            logger.info("interviewer_location_guidance_generated")
            return state

        if candidates:
            if "origin_candidate" in candidates:
                state.origin_candidate = candidates["origin_candidate"]
                if state.user_context and candidates["origin_candidate"]:
                    state.user_context.origin = candidates["origin_candidate"][0]
                    logger.info("interviewer_origin_candidate_selected")

            if "destination_candidate" in candidates:
                state.destination_candidate = candidates["destination_candidate"]
                if state.user_context and hasattr(state.user_context, "destination") and candidates["destination_candidate"]:
                    state.user_context.destination = candidates["destination_candidate"][0]
                    logger.info("interviewer_destination_candidate_selected")

            if "waypoint_candidates" in candidates:
                waypoint_candidates: dict = candidates["waypoint_candidates"]
                if state.user_context and hasattr(state.user_context, "waypoints"):
                    waypoints = state.user_context.waypoints
                    if state.waypoint_candidates is None:
                        state.waypoint_candidates = [None] * len(waypoints)
                    for idx, locs in waypoint_candidates.items():
                        if idx >= len(state.waypoint_candidates):
                            state.waypoint_candidates.extend(
                                [None] * (idx + 1 - len(state.waypoint_candidates))
                            )
                        state.waypoint_candidates[idx] = locs
                        if locs and idx < len(waypoints):
                            waypoints[idx] = locs[0]
                            logger.info("interviewer_waypoint_candidate_selected | index=%d", idx)

            is_complete = self._is_complete(state.user_context)
            await self._update_shortest_km(state)
            logger.info(f"is_complete을 재확인합니다: is_complete = {is_complete}")
            logger.info(f"shortest_km: {state.shortest_km}")

            if is_complete and self._is_oneway_shortest_conflict(state):
                state.is_complete = False
                state.response = await self._generate_response(
                    state, missing_info="", shortest_km_conflict=state.shortest_km,
                )
                logger.info("interviewer_oneway_shortest_conflict | shortest_km=%s", state.shortest_km)
                return state

            # 장소 검색 후 정보가 충분해진 경우 → 확인 질문
            if is_complete:
                state.awaiting_confirmation = True
                state.is_complete           = False
                state.response = await self._generate_response(state, missing_info="")
                logger.info("interviewer_confirmation_pending")
                return state

            # 검색으로 확정된 origin/destination을 반영해 interview.yaml을 다시 호출한다.
            response = await self._generate_response(state, self._get_missing_info(state.user_context))
            logger.info("interview.yaml이 검색 결과 반영을 위해 재호출되었습니다.")
        else:
            response = raw_response.content

        state.is_complete = False
        state.response    = response

        logger.info("interviewer_response_generated")

        return state

    def _build_input_variables(
        self,
        state: State,
        missing_info: str,
        search_failures: Optional[dict[str, str]] = None,
        out_of_seoul: Optional[dict[str, str]] = None,
        shortest_km_conflict: Optional[float] = None,
    ) -> dict:
        return {
            "current_context":  self.prompt_utils.format_for_prompt(state.user_context),
            "current_location": self.prompt_utils.format_for_prompt(state.current_location),
            "missing_info":     missing_info,
            "search_failures":  self._describe_targets(search_failures, "검색 결과 없음"),
            "out_of_seoul":     self._describe_targets(out_of_seoul, "서울 밖"),
            "shortest_km_conflict": (
                "없음" if shortest_km_conflict is None else f"최단거리 {shortest_km_conflict}km"
            ),
            "user_input":       state.user_prompt,
        }

    async def _generate_response(
        self,
        state: State,
        missing_info: str,
        search_failures: Optional[dict[str, str]] = None,
        out_of_seoul: Optional[dict[str, str]] = None,
        shortest_km_conflict: Optional[float] = None,
    ) -> str:
        """
        interview.yaml을 tool 미바인딩 상태(parser=str_parser)로 호출해 사용자 응답 문구를 생성한다.
        확인 질문 / 검색 실패 안내 / 서울 밖 안내 / 편도 최단거리 초과 안내 / 정보 재질문을
        전부 이 경로로 통일한다. 호출이 실패하면 내부 원문 대신 공통 안전 메시지를 반환한다.
        """
        try:
            return await super().get_response(
                prompt_name="interview",
                input_variables=self._build_input_variables(
                    state, missing_info, search_failures, out_of_seoul, shortest_km_conflict,
                ),
                parser=self.str_parser,
            )
        except Exception as exc:
            log_unexpected_error(logger, "interviewer_response_llm_error", exc)
            return SAFE_INTERNAL_ERROR_DETAIL

    @staticmethod
    def _target_label(key: str) -> str:
        if key == "origin":
            return "출발지"
        if key == "destination":
            return "목적지"
        if key.startswith("waypoint_"):
            idx = key.split("_", 1)[1]
            return f"{int(idx) + 1}번째 경유지" if idx.isdigit() else "경유지"
        return key

    def _describe_targets(self, targets: Optional[dict[str, str]], reason: str) -> str:
        """
        {target: keyword} 딕셔너리를 LLM 입력용 자연어 설명으로 변환한다.
        (LLM 응답을 대체하는 것이 아니라 LLM에 전달할 입력을 구성하는 것)
        """
        if not targets:
            return "없음"
        parts = [f"{self._target_label(key)}('{keyword}') {reason}" for key, keyword in targets.items()]
        return "; ".join(parts)

    async def _update_shortest_km(self, state: State) -> None:
        """
        편도 우회(oneway_random)·최단(oneway_shortest) 두 모드 모두에서, 출발지·목적지
        위경도가 둘 다 확정되면 물리적 최단거리를 계산해 state.shortest_km에 채운다.
        state.route_result는 oneway_shortest에서만 같이 채운다.

        - oneway_shortest: 이 결과가 곧 최종 경로다. route_executor와 똑같이
          RouteTool.oneway_shortest_route(비동기, asyncio.to_thread + 타임아웃)를 통해
          생성한다 — RouteService.get_route()를 이 async 노드에서 직접 동기 호출하면
          POI 조회·RouteHistory 저장 같은 DB 호출이 이벤트 루프를 막아버린다. 인증
          확인·POI 조회·RouteHistory 저장까지 마친 결과라 route_executor가 재계산 없이
          그대로 재사용하므로 state.route_result도 같이 채운다.
        - oneway_random: 목표 거리와 비교할 참고용 거리(숫자)만 필요하고 최종 경로는
          GRASP+ALNS로 따로 생성되어 이 A* 결과 자체는 버려지므로, route_service의
          가벼운 get_shortest_km(인증·POI·저장 없음, Optional[float])만 쓰고
          state.route_result는 채우지 않는다(route_executor가 실행되면 항상 새로
          덮어쓰므로 미리 채워도 의미가 없다).

        그 외(다른 모드로 바뀜, 위치 미확정, 경로 없음)와 oneway_random에서는 둘 다
        None으로 지운다 — prewalk_service.py의 orchestrator가 더 이상 매 턴
        route_result를 초기화하지 않으므로(2026-09-23), 여기서 적용 대상이 아닌 경우를
        항상 명시적으로 지우지 않으면 이전 턴·이전 모드의 값이 다음 턴까지 stale하게
        남는다. is_complete 판정이 바뀔 수 있는 지점(run() 안 두 곳)마다 호출해, 이번
        턴 기준으로 항상 최신 상태를 유지한다.
        """
        pref = state.user_context
        if not isinstance(pref, (OnewayPreference, OnewayShortestPreference)):
            state.shortest_km  = None
            state.route_result = None
            return
        if not self._has_location(pref.origin) or not self._has_location(pref.destination):
            state.shortest_km  = None
            state.route_result = None
            return

        origin      = Coordinate(lat=pref.origin.lat, lon=pref.origin.lon)
        destination = Coordinate(lat=pref.destination.lat, lon=pref.destination.lon)

        if pref.mode != WalkMode.ONEWAY_SHORTEST:
            state.shortest_km  = self.route_service.get_shortest_km(origin, destination)
            state.route_result = None
            return

        try:
            results = await self.route_tool.tool_map[MODE_TOOL_MAP[WalkMode.ONEWAY_SHORTEST]].ainvoke({
                "origin":            origin,
                "destination":       destination,
                "access_token":      state.access_token or "",
                "origin_label":      PlaceLabel(address=pref.origin.address, place_name=pref.origin.place_name),
                "destination_label": PlaceLabel(address=pref.destination.address, place_name=pref.destination.place_name),
            })
        except Exception as exc:
            log_unexpected_error(logger, "interviewer_shortest_route_error", exc)
            state.shortest_km  = None
            state.route_result = None
            return

        result = results[0] if results else None
        if result is None or result.status != WalkRouteStatus.SUCCESS:
            state.shortest_km  = None
            state.route_result = None
            return

        state.shortest_km  = result.total_km
        state.route_result = results

    @staticmethod
    def _is_oneway_shortest_conflict(state: State) -> bool:
        """
        편도 우회(oneway_random)에서, 목표 거리가 state.shortest_km(직전에 `_update_shortest_km`가
        채운 값) 이하면(=우회할 여지가 없는 요청) True. 다른 모드거나 target_km/shortest_km이
        아직 없으면 False — oneway_shortest는 애초에 target_km 필드 자체가 없어 "충돌"이라는
        개념이 성립하지 않는다(단지 참고용 거리로 state.shortest_km만 채워질 뿐).
        """
        pref = state.user_context
        if not isinstance(pref, OnewayPreference):
            return False
        if pref.target_km is None or state.shortest_km is None:
            return False
        return pref.target_km <= state.shortest_km

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
        elif isinstance(pref, GPSArtPreference):
            return self._has_location(pref.origin) and pref.target_km is not None and bool(pref.shape)
        elif isinstance(pref, WayPointPreference):
            if not self._has_location(pref.origin) or not self._has_location(pref.destination):
                return False
            if any(not self._has_location(wp) for wp in pref.waypoints):
                return False
            return all(leg.target_km is not None for leg in pref.legs if leg.mode == "oneway_random")
        else:
            return self._has_location(pref.origin) and pref.target_km is not None

    def _get_missing_info(self, pref: Optional[BasePreference]) -> str:
        if pref is None:
            return "출발지, 목적지(편도인 경우), 목표 거리, 경로 유형"

        missing = []
        if not self._has_location(pref.origin):
            missing.append("출발지 장소명 또는 좌표")
        if isinstance(pref, (OnewayPreference, OnewayShortestPreference, WayPointPreference)):
            if not self._has_location(pref.destination):
                missing.append("목적지 장소명 또는 좌표")
        if isinstance(pref, (CircularPreference, OnewayPreference, GPSArtPreference)):
            if pref.target_km is None:
                missing.append("목표 거리")
        if isinstance(pref, GPSArtPreference):
            if not pref.shape:
                missing.append("그리고 싶은 도형(모양)")
        if isinstance(pref, WayPointPreference):
            if any(not self._has_location(wp) for wp in pref.waypoints):
                missing.append("경유지 장소명 또는 좌표")
            if any(leg.mode == "oneway_random" and leg.target_km is None for leg in pref.legs):
                missing.append("우회 구간의 목표 거리")

        return ", ".join(missing) if missing else ""

    async def _safe_kakao_call(self, coro):
        """
        Kakao API 호출을 감싸 예외 발생 시 (None, 예외)를 반환합니다.
        """
        try:
            result = await coro
            return result, None
        except Exception as exc:
            log_unexpected_error(logger, "kakao_api_error", exc)
            return None, exc

    async def _execute_tool_calls(self, tool_calls: list, state: State) -> tuple[dict, dict, dict, Optional[str]]:
        candidates      = {}
        search_failures = {}  # target("origin"/"destination") -> 검색했지만 결과 없던 키워드
        out_of_seoul    = {}  # target("origin"/"destination") -> 검색은 됐지만 전부 서울 밖이던 키워드
        api_error_message: Optional[str] = None  # Kakao API 호출 자체가 실패했으면 안전한 공통 문구

        fallback_lat = (
            (state.user_context.origin.lat if state.user_context and state.user_context.origin else None)
            or state.current_location.lat
        )
        fallback_lon = (
            (state.user_context.origin.lon if state.user_context and state.user_context.origin else None)
            or state.current_location.lon
        )

        # circular 모드는 destination 필드 자체가 없어 검색 대상이 항상 origin이다.
        # (LLM이 target을 잘못 태깅하거나 명시적으로 null을 보내는 경우까지 방어)
        has_destination = hasattr(state.user_context, "destination")

        # 1. LLM이 요청한 tool calls 처리
        for call in tool_calls:
            name, args = call["name"], call["args"]
            target = args.get("target") or "destination"
            if not has_destination:
                target = "origin"

            # waypoint는 여러 개일 수 있어 waypoint_index로 구분하고, 실패 결과도 인덱스별로 구분한다.
            waypoint_index = args.get("waypoint_index") if target == "waypoint" else None
            if target == "waypoint" and not isinstance(waypoint_index, int):
                waypoint_index = 0
            failure_key = f"waypoint_{waypoint_index}" if target == "waypoint" else target

            if not args.get("lat") or not args.get("lon"):
                args["lat"] = fallback_lat
                args["lon"] = fallback_lon

            output, error = await self._safe_kakao_call(
                self.place_tool.tool_map[name].ainvoke(args)
            )
            if error is not None:
                api_error_message = SAFE_INTERNAL_ERROR_DETAIL
                continue

            logger.info(
                "interviewer_location_search_completed | target=%s | count=%d",
                target,
                len(output.documents) if isinstance(output, PlaceSearchResult) else 0,
            )

            if isinstance(output, PlaceSearchResult) and output.documents:
                if target == "origin":
                    fallback_lat = float(output.documents[0].y)
                    fallback_lon = float(output.documents[0].x)

                seoul_docs = [
                    Location(lat=float(d.y), lon=float(d.x), address=d.address_name, place_name=d.place_name)
                    for d in output.documents
                    if is_within_seoul_bbox(float(d.y), float(d.x))
                ]
                if seoul_docs:
                    if target == "waypoint":
                        candidates.setdefault("waypoint_candidates", {})[waypoint_index] = seoul_docs
                    else:
                        candidates[f"{target}_candidate"] = seoul_docs
                else:
                    out_of_seoul[failure_key] = args.get("keyword") or args.get("category") or ""
            else:
                search_failures[failure_key] = args.get("keyword") or args.get("category") or ""

        # 2. place_name은 있지만 좌표가 없는 location 자동 보완
        if state.user_context:
            origin = state.user_context.origin
            # origin 자동 보완
            if origin and origin.place_name and origin.lat is None and "origin_candidate" not in candidates:
                result, error = await self._safe_kakao_call(
                    self.place_tool.get_address_from_keyword(
                        keyword=origin.place_name, lat=fallback_lat, lon=fallback_lon
                    )
                )
                if error is not None:
                    api_error_message = SAFE_INTERNAL_ERROR_DETAIL
                elif isinstance(result, PlaceSearchResult) and result.documents:
                    fallback_lat = float(result.documents[0].y)
                    fallback_lon = float(result.documents[0].x)

                    seoul_docs = [
                        Location(lat=float(d.y), lon=float(d.x), address=d.address_name, place_name=d.place_name)
                        for d in result.documents
                        if is_within_seoul_bbox(float(d.y), float(d.x))
                    ]
                    if seoul_docs:
                        candidates["origin_candidate"] = seoul_docs
                    else:
                        out_of_seoul["origin"] = origin.place_name
                else:
                    search_failures["origin"] = origin.place_name

            # destination 자동 보완
            if hasattr(state.user_context, "destination"):
                dest = state.user_context.destination
                if dest and dest.place_name and dest.lat is None and "destination_candidate" not in candidates:
                    result, error = await self._safe_kakao_call(
                        self.place_tool.get_address_from_keyword(
                            keyword=dest.place_name, lat=fallback_lat, lon=fallback_lon
                        )
                    )
                    if error is not None:
                        api_error_message = SAFE_INTERNAL_ERROR_DETAIL
                    elif isinstance(result, PlaceSearchResult) and result.documents:
                        seoul_docs = [
                            Location(lat=float(d.y), lon=float(d.x), address=d.address_name, place_name=d.place_name)
                            for d in result.documents
                            if is_within_seoul_bbox(float(d.y), float(d.x))
                        ]
                        if seoul_docs:
                            candidates["destination_candidate"] = seoul_docs
                        else:
                            out_of_seoul["destination"] = dest.place_name
                    else:
                        search_failures["destination"] = dest.place_name

            # waypoints 자동 보완 (place_name은 있지만 좌표가 없는 항목만)
            if hasattr(state.user_context, "waypoints"):
                waypoint_candidates: dict = candidates.get("waypoint_candidates", {})
                for idx, wp in enumerate(state.user_context.waypoints):
                    if not (wp and wp.place_name and wp.lat is None and idx not in waypoint_candidates):
                        continue
                    result, error = await self._safe_kakao_call(
                        self.place_tool.get_address_from_keyword(
                            keyword=wp.place_name, lat=fallback_lat, lon=fallback_lon
                        )
                    )
                    if error is not None:
                        api_error_message = SAFE_INTERNAL_ERROR_DETAIL
                    elif isinstance(result, PlaceSearchResult) and result.documents:
                        seoul_docs = [
                            Location(lat=float(d.y), lon=float(d.x), address=d.address_name, place_name=d.place_name)
                            for d in result.documents
                            if is_within_seoul_bbox(float(d.y), float(d.x))
                        ]
                        if seoul_docs:
                            waypoint_candidates[idx] = seoul_docs
                        else:
                            out_of_seoul[f"waypoint_{idx}"] = wp.place_name
                    else:
                        search_failures[f"waypoint_{idx}"] = wp.place_name
                if waypoint_candidates:
                    candidates["waypoint_candidates"] = waypoint_candidates

        return candidates, search_failures, out_of_seoul, api_error_message
