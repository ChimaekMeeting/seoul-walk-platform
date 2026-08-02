import json, logging
from typing import Optional
from langchain_core.output_parsers import StrOutputParser
from src.schema.prewalk_schema import State, Location
from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils
from src.agent.tools.mode_tools import ModeTool

logger = logging.getLogger(__name__)

class Extractor(GPTClient):
    def __init__(self):
        super().__init__()
        self.mode_tool    = ModeTool()
        self.model        = self.llm.bind_tools(self.mode_tool.tools)
        self.prompt_utils = PromptUtils()
        self.str_parser   = StrOutputParser()

    async def run(self, state: State) -> State:
        """
        모드/위치 추출(tool_call) 후 테마 태그를 추출해 State에 저장합니다.
        """
        input_variables = {
            "user_input":             state.user_prompt,
            "current_context":        self.prompt_utils.format_for_prompt(state.user_context),
        }

        # extractor 응답 생성
        try:
            res = await super().get_response(
                prompt_name     = "extraction",
                input_variables = input_variables,
                llm             = self.model,
            )
        except Exception:
            logger.exception("extractor_llm_error")
            return state

        # 예외1. 산책 모드를 결정하지 못한 경우
        if not res or not res.tool_calls:
            logger.warning("LLM이 산책 모드를 결정하지 못했습니다.")
            return state

        tool_call = res.tool_calls[0]
        tool_name = tool_call["name"]  # LLM이 결정한 산책 모드

        # 예외2. 정의되지 않은 산책 모드를 사용하는 경우
        if tool_name not in self.mode_tool.tool_map:
            logger.warning(f"LLM이 정의되지 않은 산책 모드를 사용합니다: {tool_name}")
            return state

        # LLM이 추출한 산책 모드 외 정보
        args = tool_call["args"]
        prior_context = state.user_context  # 이번 턴 추출 전 State(직전 place_name과 비교하기 위함)

        # 예외3. LLM이 place_name과 함께 스스로 채운 좌표를 검증한다.
        #   - 직전 place_name과 다르면(새로 언급된 장소) 좌표를 지워 Interviewer의 Kakao 재검증을 강제한다.
        #     실시간 검증이 안 된 값이라 서울 밖 좌표를 그대로 들고 확인 단계까지 갈 수 있다(is_within_seoul_bbox 우회).
        #   - 직전 place_name과 같으면(같은 장소 재언급) 새로 채운 좌표 대신 직전에 이미 확정된 좌표로 덮어써
        #     불필요한 재검색과 LLM의 이번 턴 헛채움을 함께 막는다.
        #   - 현재 위치와 정확히 일치하는 좌표("여기"/"현재 위치" 처리)는 그대로 신뢰한다.
        self._reconcile_location_arg(
            args.get("origin"),
            prior_context.origin if prior_context else None,
            state.current_location,
        )
        self._reconcile_location_arg(
            args.get("destination"),
            getattr(prior_context, "destination", None) if prior_context else None,
            state.current_location,
        )

        # 예외4. origin과 destination이 동일한 장소명인데 명시적 출발지 표현이 없는 경우
        # (e.g., "용산역으로 가는 길 알려줘" → origin을 null로 보정해 현재 위치로 대체)
        _EXPLICIT_ORIGIN_MARKERS = ("에서", "부터", "출발", "시작")
        origin_arg = args.get("origin")
        dest_arg   = args.get("destination")
        if origin_arg and dest_arg:
            # LLM이 dict 대신 장소명 문자열만 넘기는 경우도 있어 두 형태 모두 처리한다.
            origin_name = origin_arg.get("place_name") if isinstance(origin_arg, dict) else origin_arg if isinstance(origin_arg, str) else None
            dest_name   = dest_arg.get("place_name")   if isinstance(dest_arg,   dict) else dest_arg   if isinstance(dest_arg,   str) else None
            if origin_name and dest_name and origin_name == dest_name:
                if not any(m in state.user_prompt for m in _EXPLICIT_ORIGIN_MARKERS):
                    args["origin"] = None
                    logger.warning(
                        f"origin과 destination이 동일한 장소명({origin_name})이며 "
                        f"명시적 출발지 표현이 없어 origin을 null로 보정합니다."
                    )

        # 예외5. 출발지가 없는 경우
        if args.get("origin") is None:
            args["origin"] = state.current_location.model_dump()
            logger.warning(f"출발지가 정해지지 않아, 현 위치를 출발지로 설정합니다: {args['origin']}")

        # 예외6. tool 호출 자체가 실패하는 경우(예: LLM이 예상 밖 형식의 인자를 채운 경우)
        try:
            pref = self.mode_tool.tool_map[tool_name].invoke(args)
        except Exception:
            logger.exception(f"산책 모드 도구 호출에 실패했습니다: tool_name={tool_name}, args={args}")
            return state

        state.mode         = pref.mode
        state.user_context = pref
        state.themes       = await self._extract_themes(state.user_prompt)

        # 로그
        logger.info(f"user_prompt: {state.user_prompt}")
        logger.info(f"mode: {state.mode}")
        logger.info(f"user_context: {state.user_context.model_dump_json() if state.user_context else None}")
        logger.info(f"themes: {state.themes}")

        return state

    @staticmethod
    def _reconcile_location_arg(
        loc_arg,
        prior_loc: Optional[Location],
        current_location: Location,
    ) -> None:
        """
        LLM이 tool 호출 인자에 채운 좌표를 검증한다.
        - 현재 위치와 정확히 일치하면 그대로 둔다("여기"/"현재 위치" 처리).
        - place_name이 직전 State 값과 같다면(같은 장소 재언급) 새로 채운(또는 빈) 좌표 대신
          직전에 이미 확정된 좌표로 덮어써 불필요한 재검색과 LLM의 헛채움을 함께 막는다.
        - place_name이 다르거나 비교할 직전 값이 없다면(새로 언급된 장소) 좌표를 지워
          place_name만 남기고 Interviewer의 Kakao 검색·bbox 검증을 강제한다.
        """
        if not isinstance(loc_arg, dict):
            return

        place_name = loc_arg.get("place_name")
        lat, lon   = loc_arg.get("lat"), loc_arg.get("lon")

        if (
            lat is not None and lon is not None
            and current_location.lat is not None and current_location.lon is not None
            and abs(lat - current_location.lat) < 1e-6
            and abs(lon - current_location.lon) < 1e-6
        ):
            return

        if (
            prior_loc is not None
            and prior_loc.place_name is not None
            and place_name == prior_loc.place_name
        ):
            loc_arg["lat"]     = prior_loc.lat
            loc_arg["lon"]     = prior_loc.lon
            loc_arg["address"] = prior_loc.address
            return

        loc_arg["lat"]     = None
        loc_arg["lon"]     = None
        loc_arg["address"] = None

    async def _extract_themes(self, user_input: str) -> list[str]:
        """
        발화에서 TAG_WEIGHT_MAP 키에 해당하는 테마 태그를 0~3개 추출합니다.
        LLM 응답 파싱 실패 시 빈 리스트를 반환합니다.
        """
        from src.service.user.survey_service import TAG_WEIGHT_MAP  # 순환 import 방지(지연 로드)

        tag_keys = list(TAG_WEIGHT_MAP.keys())
        try:
            res = await super().get_response(
                prompt_name     = "themes",
                input_variables = {"user_input": user_input, "tag_keys": tag_keys},
                parser          = self.str_parser,
            )
            tags = json.loads(res)
            return [t for t in tags if t in TAG_WEIGHT_MAP]
        except Exception:
            logger.warning("사용자 프롬프트에서 테마를 추출하지 못했습니다.")
            return []
