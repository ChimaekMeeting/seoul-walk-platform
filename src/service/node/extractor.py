from langchain_core.output_parsers import PydanticOutputParser

from src.schema.prewalk_schema import UserPreferenceContext
from src.client.gpt_client import GPTClient
from src.service.common.utils import PromptUtils

class Extractor(GPTClient):
    def __init__(self):
        super().__init__()
        self.parser = PydanticOutputParser(pydantic_object=UserPreferenceContext)
        self.prompt_utils = PromptUtils()

    async def run(self, state):
        """
        사용자의 입력에서 정보를 추출하여 context를 업데이트합니다.
        """
        input_variables = {
            "user_input": state.get("user_prompt", ""),
            "current_context": self.prompt_utils.format_for_prompt(state.get("user_context", {})),
            "current_location": self.prompt_utils.format_for_prompt(state.get("current_location", {})),
            "origin_candidates": self.prompt_utils.format_for_prompt(state.get("origin_candidate")),
            "destination_candidates": self.prompt_utils.format_for_prompt(state.get("destination_candidate")),
            "format_instructions": self.parser.get_format_instructions()
        }

        return await super().get_response(
            prompt_name="extraction",
            input_variables=input_variables,
            parser=self.parser
        )