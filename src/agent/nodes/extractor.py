from src.schema.prewalk_schema import State, Location
from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.utils.chatbot_utils import PromptUtils
from src.agent.tools.mode_tools import ModeTool


class Extractor(GPTClient):
    def __init__(self):
        super().__init__()
        self.mode_tool    = ModeTool()
        self.model        = self.llm.bind_tools(self.mode_tool.tools)
        self.prompt_utils = PromptUtils()

    async def run(self, state: State) -> State:
        """
        정보를 수집합니다.
        """
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

        # LLM이 산책 모드를 택하지 않은 경우
        if not res or not res.tool_calls:  return state

        # LLM이 산책 모드를 잘못 택한 경우
        tool_call = res.tool_calls[0]
        tool_name = tool_call["name"]
        if tool_name not in self.mode_tool.tool_map:  return state

        args               = tool_call["args"]  # tool에 들어갈 인자
        pref               = self.mode_tool.tool_map[tool_name].invoke(args)  # tool 사용 결과
        pref.purpose       = state.user_context.purpose if state.user_context else None
        state.mode         = pref.mode
        state.user_context = pref

        return state
