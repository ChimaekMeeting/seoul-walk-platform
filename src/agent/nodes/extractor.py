import json, logging
from langchain_core.output_parsers import StrOutputParser
from src.schema.prewalk_schema import State, Location
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
            "current_location":       self.prompt_utils.format_for_prompt(state.current_location),
            "origin_candidates":      self.prompt_utils.format_for_prompt(state.origin_candidate),
            "destination_candidates": self.prompt_utils.format_for_prompt(state.destination_candidate),
        }

        # extractor 응답 생성
        res = await super().get_response(
            prompt_name     = "extraction",
            input_variables = input_variables,
            llm             = self.model,
        )

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

        # 예외3. 출발지가 없는 경우
        if args.get("origin") is None:
            args["origin"] = state.current_location.model_dump()
            logger.warning(f"출발지가 정해지지 않아, 현 위치를 출발지로 설정합니다: {args['origin']}")

        pref               = self.mode_tool.tool_map[tool_name].invoke(args)
        pref.purpose       = state.user_context.purpose if state.user_context else None
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
        res = await super().get_response(
            prompt_name     = "themes",
            input_variables = {"user_input": user_input, "tag_keys": tag_keys},
            parser          = self.str_parser,
        )
        try:
            tags = json.loads(res)
            return [t for t in tags if t in TAG_WEIGHT_MAP]
        except Exception:
            logger.warning("사용자 프롬프트에서 테마를 추출하지 못했습니다.")
            return []
