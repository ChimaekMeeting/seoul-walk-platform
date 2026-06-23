import json
from langchain_core.output_parsers import StrOutputParser
from src.schema.prewalk_schema import State, Location
from src.interfaces.schema.walk_schema import CircularMode, OnewayMode
from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils
from src.agent.tools.mode_tools import ModeTool
from src.service.user.survey_service import TAG_WEIGHT_MAP


class Extractor(GPTClient):
    """사용자 발화에서 산책 모드·위치·테마를 추출하는 에이전트 노드."""
    def __init__(self):
        super().__init__()
        self.mode_tool    = ModeTool()
        self.model        = self.llm.bind_tools(self.mode_tool.tools)
        self.prompt_utils = PromptUtils()
        self.str_parser   = StrOutputParser()

    async def run(self, state: State) -> State:
        """모드/위치 추출(tool_call) 후 테마 태그를 추출해 State에 저장합니다."""
        input_variables = {
            "user_input":             state.user_prompt,
            "current_context":        self.prompt_utils.format_for_prompt(state.user_context),
            "current_location":       self.prompt_utils.format_for_prompt(state.current_location),
            "origin_candidates":      self.prompt_utils.format_for_prompt(state.origin_candidate),
            "destination_candidates": self.prompt_utils.format_for_prompt(state.destination_candidate),
        }

        res = await super().get_response(
            prompt_name     = "extraction",
            input_variables = input_variables,
            llm             = self.model,
        )

        if not res or not res.tool_calls:  return state

        tool_call = res.tool_calls[0]
        tool_name = tool_call["name"]
        if tool_name not in self.mode_tool.tool_map:  return state

        args = tool_call["args"]
        if args.get("origin") is None:
            args["origin"] = state.current_location.model_dump()

        pref               = self.mode_tool.tool_map[tool_name].invoke(args)
        pref.purpose       = state.user_context.purpose if state.user_context else None
        state.mode         = pref.mode
        state.user_context = pref
        state.themes       = await self._extract_themes(state.user_prompt)

        return state

    async def _extract_themes(self, user_input: str) -> list[str]:
        """
        발화에서 TAG_WEIGHT_MAP 키에 해당하는 테마 태그를 0~3개 추출합니다.
        LLM 응답 파싱 실패 시 빈 리스트를 반환합니다.
        """
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
            return []
