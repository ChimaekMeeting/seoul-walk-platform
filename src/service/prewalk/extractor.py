from src.schema.prewalk_schema import (
    WalkPreferenceExtraction,
    State
)
from src.client.gpt_client import GPTClient
from src.service.prewalk.chatbot_utils import PromptUtils

class Extractor(GPTClient):
    def __init__(self):
        super().__init__()

        # binding이 format_instructions보다 더 강력
        self.model = self.llm.with_structured_output(
            WalkPreferenceExtraction
        )
        self.prompt_utils = PromptUtils()

    async def run(self, state: State) -> State:
        """
        사용자의 입력에서 정보를 추출하여 context를 업데이트합니다.
        """
        input_variables = {
            "user_input": state.user_prompt,
            "current_context": self.prompt_utils.format_for_prompt(state.user_context),
            "current_location": self.prompt_utils.format_for_prompt(state.current_location),
            "origin_candidates": self.prompt_utils.format_for_prompt(state.origin_candidate),
            "destination_candidates": self.prompt_utils.format_for_prompt(state.destination_candidate),
        }

        res = await super().get_response(
            prompt_name="extraction",
            input_variables=input_variables,
            llm=self.model
        )

        if res and hasattr(res, "preference"):
            state.user_context = res.preference
        else:
            state.user_context = res

        return state