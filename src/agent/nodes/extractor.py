import json, logging
from langchain_core.output_parsers import StrOutputParser
from src.schema.prewalk_schema import State
from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils
from src.agent.tools.mode_tools import ModeTool

logger = logging.getLogger(__name__)

class Extractor(GPTClient):
    """
    사용자 발화에서 산책 모드·위치·테마를 추출하는 에이전트 노드.
    """
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
            "current_location":       self.prompt_utils.format_for_prompt(state.current_location)
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

        # 예외3. origin과 destination이 동일한 장소명인데 명시적 출발지 표현이 없는 경우
        # (e.g., "용산역으로 가는 길 알려줘" → origin을 null로 보정해 현재 위치로 대체)
        _EXPLICIT_ORIGIN_MARKERS = ("에서", "부터", "출발", "시작")
        origin_arg = args.get("origin")
        dest_arg   = args.get("destination")
        if origin_arg and dest_arg:
            origin_name = origin_arg.get("place_name") if isinstance(origin_arg, dict) else None
            dest_name   = dest_arg.get("place_name")   if isinstance(dest_arg,   dict) else None
            if origin_name and dest_name and origin_name == dest_name:
                if not any(m in state.user_prompt for m in _EXPLICIT_ORIGIN_MARKERS):
                    args["origin"] = None
                    logger.warning(
                        f"origin과 destination이 동일한 장소명({origin_name})이며 "
                        f"명시적 출발지 표현이 없어 origin을 null로 보정합니다."
                    )

        # 예외4. 출발지가 없는 경우
        if args.get("origin") is None:
            args["origin"] = state.current_location.model_dump()
            logger.warning(f"출발지가 정해지지 않아, 현 위치를 출발지로 설정합니다: {args['origin']}")

        # 예외5. GPS Art 모드인데 목표 거리가 없는 경우
        if tool_name == "select_gps_art" and not args.get("target_km"):
            args["target_km"] = 3.0
            logger.warning("GPS Art 모드의 목표 거리가 정해지지 않아, 기본값 3.0km로 설정합니다.")

        pref               = self.mode_tool.tool_map[tool_name].invoke(args)
        state.mode         = pref.mode
        state.user_context = pref
        state.themes       = await self._extract_themes(state.user_prompt)

        # 로그
        logger.info(f"user_prompt: {state.user_prompt}")
        logger.info(f"mode: {state.mode}")
        logger.info(f"user_context: {state.user_context.model_dump_json() if state.user_context else None}")
        logger.info(f"themes: {state.themes}")

        return state

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
