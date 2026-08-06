from langchain_core.output_parsers import StrOutputParser
from typing import Optional
import logging

from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.tools.place_tools import PlaceTool
from src.infrastructure.external.schema.place_schema import PlaceSearchResult
from src.agent.utils.chatbot_utils import PromptUtils
from src.interfaces.validators.coord_validator import is_within_seoul_bbox
from src.schema.prewalk_schema import (
    State,
    Location,
    BasePreference,
    CircularPreference,
    OnewayPreference,
    OnewayShortestPreference,
    GPSArtPreference,
)

_FALLBACK_RESPONSE = "죄송해요, 일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요."
_KAKAO_API_ERROR_RESPONSE = "내부적으로 오류가 발생했어요. 잠시 후 다시 시도해 주세요."

logger = logging.getLogger(__name__)

class Interviewer(GPTClient):
    def __init__(self):
        super().__init__()
        self.place_tool   = PlaceTool()
        self.prompt_utils = PromptUtils()
        self.model        = self.llm.bind_tools(self.place_tool.tools)
        self.str_parser   = StrOutputParser()

    async def run(self, state: State) -> State:
        """
        정보가 부족하다면 → 질문을 던지고
        정보가 충분하면   → 확인 메시지를 생성한다(경로는 사용자 확인 후 실행).
        """
        is_complete  = self._is_complete(state.user_context)
        missing_info = self._get_missing_info(state.user_context)

        logger.info(f"is_complete: {is_complete}")
        logger.info(f"missing_info: {missing_info}")

        input_variables = {
            "current_context":  self.prompt_utils.format_for_prompt(state.user_context),
            "current_location": self.prompt_utils.format_for_prompt(state.current_location),
            "missing_info":     missing_info,
            "user_input":       state.user_prompt,
        }

        # 정보가 충분하면 → 사용자 확인 질문 생성 (경로 실행은 확인 후)
        if is_complete:
            state.awaiting_confirmation = True
            state.is_complete           = False
            state.response              = self._build_confirmation_message(state)
            logger.info(f"확인 대기 상태로 전환합니다: {state.response}")
            return state

        # 정보가 부족하면 → interview.yaml 호출
        try:
            raw_response = await super().get_response(
                prompt_name="interview",
                input_variables=input_variables,
                llm=self.model,
            )
        except Exception:
            logger.exception("interviewer_interview_llm_error")
            state.response = _FALLBACK_RESPONSE
            return state
        logger.info("interview.yaml이 호출되었습니다.")

        candidates, search_failures, out_of_seoul, api_error = await self._execute_tool_calls(
            raw_response.tool_calls if raw_response.tool_calls else [],
            state,
        )

        # Kakao API 호출 자체가 예외로 실패했으면, 검색 결과 판단 없이 바로 내부 오류 안내로 재질문한다.
        if api_error:
            state.is_complete = False
            state.response    = _KAKAO_API_ERROR_RESPONSE
            logger.info("Kakao API 호출 중 오류가 발생했습니다.")
            return state

        # 검색 결과는 있지만 전부 서울 밖이면, LLM 문구 생성 없이 하드코딩 안내로 바로 재질문한다.
        if out_of_seoul:
            state.is_complete = False
            state.response    = self._build_out_of_seoul_message(out_of_seoul)
            logger.info(f"검색 결과가 서울 밖입니다: {out_of_seoul}")
            return state

        # 검색 결과가 0건인 대상이 있으면, LLM 문구 생성 없이 하드코딩 안내로 바로 재질문한다.
        # (origin=destination 동일 처리 같은 무관한 이유로 재질문하는 오해를 막기 위함)
        if search_failures:
            state.is_complete = False
            state.response    = self._build_search_failure_message(search_failures)
            logger.info(f"장소 검색 결과 없음: {search_failures}")
            return state

        if candidates:
            if "origin_candidate" in candidates:
                state.origin_candidate = candidates["origin_candidate"]
                if state.user_context and candidates["origin_candidate"]:
                    state.user_context.origin = candidates["origin_candidate"][0]
                    logger.info(f"origin_candidate: {candidates['origin_candidate']}")
                    logger.info(f"origin: {state.user_context.origin}")

            if "destination_candidate" in candidates:
                state.destination_candidate = candidates["destination_candidate"]
                if state.user_context and hasattr(state.user_context, "destination") and candidates["destination_candidate"]:
                    state.user_context.destination = candidates["destination_candidate"][0]
                    logger.info(f"destination_candidate: {candidates['destination_candidate']}")
                    logger.info(f"destination: {state.user_context.destination}")

            is_complete = self._is_complete(state.user_context)
            logger.info(f"is_complete을 재확인합니다: is_complete = {is_complete}")

            # 장소 검색 후 정보가 충분해진 경우 → 확인 질문
            if is_complete:
                state.awaiting_confirmation = True
                state.is_complete           = False
                state.response              = self._build_confirmation_message(state)
                logger.info(f"확인 대기 상태로 전환합니다: {state.response}")
                return state

            try:
                # 검색으로 확정된 origin/destination을 반영해 interview.yaml을 다시 호출한다.
                # llm= 대신 parser=만 넘겨 tool 미바인딩 모델을 사용 — 재검색을 원천 차단한다.
                response = await super().get_response(
                    prompt_name="interview",
                    input_variables={
                        "current_context":  self.prompt_utils.format_for_prompt(state.user_context),
                        "current_location": self.prompt_utils.format_for_prompt(state.current_location),
                        "missing_info":     self._get_missing_info(state.user_context),
                        "user_input":       state.user_prompt,
                    },
                    parser=self.str_parser,
                )
            except Exception:
                logger.exception("interviewer_interview_followup_llm_error")
                response = _FALLBACK_RESPONSE
            logger.info("interview.yaml이 검색 결과 반영을 위해 재호출되었습니다.")
        else:
            response = raw_response.content

        state.is_complete = False
        state.response    = response

        logger.info(f"response: {state.response}")
        logger.info(f"user_context: {state.user_context.model_dump_json() if state.user_context else None}")

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
        elif isinstance(pref, GPSArtPreference):
            return self._has_location(pref.origin) and pref.target_km is not None and bool(pref.shape)
        else:
            return self._has_location(pref.origin) and pref.target_km is not None

    def _get_missing_info(self, pref: Optional[BasePreference]) -> str:
        if pref is None:
            return "출발지, 목적지(편도인 경우), 목표 거리, 경로 유형"

        missing = []
        if not self._has_location(pref.origin):
            missing.append("출발지 장소명 또는 좌표")
        if isinstance(pref, (OnewayPreference, OnewayShortestPreference)):
            if not self._has_location(pref.destination):
                missing.append("목적지 장소명 또는 좌표")
        if isinstance(pref, (CircularPreference, OnewayPreference, GPSArtPreference)):
            if pref.target_km is None:
                missing.append("목표 거리")
        if isinstance(pref, GPSArtPreference):
            if not pref.shape:
                missing.append("그리고 싶은 도형(모양)")

        return ", ".join(missing) if missing else ""

    def _is_same_location(self, a: Optional[Location], b: Optional[Location]) -> bool:
        """두 Location이 같은 지점인지 좌표 기준으로 비교합니다."""
        if a is None or b is None:
            return False
        if (a.lat is not None and b.lat is not None
                and a.lon is not None and b.lon is not None):
            return abs(a.lat - b.lat) < 1e-6 and abs(a.lon - b.lon) < 1e-6
        return False

    def _build_confirmation_message(self, state: State) -> str:
        """경로 실행 전 사용자에게 보낼 확인 질문을 생성합니다."""
        ctx     = state.user_context
        current = state.current_location

        if isinstance(ctx, (OnewayShortestPreference, OnewayPreference)):
            origin    = ctx.origin
            dest      = ctx.destination
            dest_name = dest.place_name if dest and dest.place_name else "목적지"

            if self._is_same_location(origin, current):
                return f"현재 위치부터 {dest_name}까지가 맞나요?"
            origin_name = origin.place_name if origin and origin.place_name else "현재 위치"
            return f"{origin_name}부터 {dest_name}까지가 맞나요?"

        if isinstance(ctx, CircularPreference):
            origin    = ctx.origin
            target_km = ctx.target_km or 3.0
            km_str    = str(int(target_km)) if target_km == int(target_km) else str(target_km)

            if self._is_same_location(origin, current):
                return f"현재 위치에서 출발하는 {km_str}km 순환 산책이 맞나요?"
            origin_name = origin.place_name if origin and origin.place_name else "현재 위치"
            return f"{origin_name}에서 출발하는 {km_str}km 순환 산책이 맞나요?"

        if isinstance(ctx, GPSArtPreference):
            origin    = ctx.origin
            target_km = ctx.target_km or 3.0
            km_str    = str(int(target_km)) if target_km == int(target_km) else str(target_km)
            shape_name = ctx.shape or "도형"

            if self._is_same_location(origin, current):
                return f"현재 위치에서 출발해 {shape_name} 모양으로 {km_str}km를 걷는 경로가 맞나요?"
            origin_name = origin.place_name if origin and origin.place_name else "현재 위치"
            return f"{origin_name}에서 출발해 {shape_name} 모양으로 {km_str}km를 걷는 경로가 맞나요?"

        return "이 경로로 진행할까요?"

    def _build_search_failure_message(self, search_failures: dict[str, str]) -> str:
        """
        장소 검색 결과가 0건인 대상에 맞춰 하드코딩 안내 문구를 만듭니다.
        """
        origin_kw      = search_failures.get("origin")
        destination_kw = search_failures.get("destination")

        if origin_kw and destination_kw:
            if origin_kw == destination_kw:
                return f"'{origin_kw}' 검색 결과가 없어요. 출발하고 싶으신 곳과 도착하고 싶으신 곳을 다시 알려주시면 그에 맞는 산책 경로를 준비해드리겠습니다!"
            return f"'{origin_kw}', '{destination_kw}' 모두 검색 결과가 없어요. 출발하고 싶으신 곳과 도착하고 싶으신 곳을 다시 알려주시면 그에 맞는 산책 경로를 준비해드리겠습니다!"
        if origin_kw:
            return f"'{origin_kw}' 검색 결과가 없어요. 출발하고 싶으신 다른 장소를 알려주시면 그에 맞는 산책 경로를 준비해드리겠습니다!"
        return f"'{destination_kw}' 검색 결과가 없어요. 도착하고 싶으신 다른 장소를 알려주시면 그에 맞는 산책 경로를 준비해드리겠습니다!"

    def _build_out_of_seoul_message(self, out_of_seoul: dict[str, str]) -> str:
        """
        검색은 됐지만 서울 밖인 대상에 맞춰 하드코딩 안내 문구를 만듭니다.
        """
        origin_kw      = out_of_seoul.get("origin")
        destination_kw = out_of_seoul.get("destination")

        if origin_kw and destination_kw:
            if origin_kw == destination_kw:
                return f"'{origin_kw}' 위치는 서울 밖이에요. 서울 내에서만 산책 경로를 추천해드릴 수 있어요. 출발하고 싶으신 곳과 도착하고 싶으신 곳을 다시 알려주시겠어요?"
            return f"'{origin_kw}', '{destination_kw}' 위치 모두 서울 밖이에요. 서울 내에서만 산책 경로를 추천해드릴 수 있어요. 출발하고 싶으신 곳과 도착하고 싶으신 곳을 다시 알려주시겠어요?"
        if origin_kw:
            return f"'{origin_kw}' 위치는 서울 밖이라 출발지로 사용할 수 없어요. 서울 내에서만 산책 경로를 추천해드릴 수 있어요. 출발하고 싶으신 다른 장소를 알려주시겠어요?"
        return f"'{destination_kw}' 위치는 서울 밖이라 목적지로 사용할 수 없어요. 서울 내에서만 산책 경로를 추천해드릴 수 있어요. 도착하고 싶으신 다른 장소를 알려주시겠어요?"

    async def _safe_kakao_call(self, coro):
        """
        Kakao API 호출을 감싸 예외 발생 시 (None, True)를 반환합니다.
        """
        try:
            result = await coro
            return result, False
        except Exception:
            logger.exception("kakao_api_error")
            return None, True

    async def _execute_tool_calls(self, tool_calls: list, state: State) -> tuple[dict, dict, dict, bool]:
        candidates      = {}
        search_failures = {}  # target("origin"/"destination") -> 검색했지만 결과 없던 키워드
        out_of_seoul    = {}  # target("origin"/"destination") -> 검색은 됐지만 전부 서울 밖이던 키워드
        api_error       = False  # Kakao API 호출 자체가 예외로 실패했는지

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

            if not args.get("lat") or not args.get("lon"):
                args["lat"] = fallback_lat
                args["lon"] = fallback_lon

            output, call_failed = await self._safe_kakao_call(
                self.place_tool.tool_map[name].ainvoke(args)
            )
            if call_failed:
                api_error = True
                continue

            logger.info(f"위치를 검색합니다: keyword={args.get('query', name)}, target={target}, 결과수={len(output.documents) if isinstance(output, PlaceSearchResult) else 0}")

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
                    candidates[f"{target}_candidate"] = seoul_docs
                else:
                    out_of_seoul[target] = args.get("keyword") or args.get("category") or ""
            else:
                search_failures[target] = args.get("keyword") or args.get("category") or ""

        # 2. place_name은 있지만 좌표가 없는 location 자동 보완
        if state.user_context:
            origin = state.user_context.origin
            # origin 자동 보완
            if origin and origin.place_name and origin.lat is None and "origin_candidate" not in candidates:
                result, call_failed = await self._safe_kakao_call(
                    self.place_tool.get_address_from_keyword(
                        keyword=origin.place_name, lat=fallback_lat, lon=fallback_lon
                    )
                )
                if call_failed:
                    api_error = True
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
                    result, call_failed = await self._safe_kakao_call(
                        self.place_tool.get_address_from_keyword(
                            keyword=dest.place_name, lat=fallback_lat, lon=fallback_lon
                        )
                    )
                    if call_failed:
                        api_error = True
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

        return candidates, search_failures, out_of_seoul, api_error