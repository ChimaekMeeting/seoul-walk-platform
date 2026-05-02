from langchain_core.output_parsers import PydanticOutputParser

from src.schema.prewalk_schema import UserPreferenceContext
from src.client.gpt_client import GPTClient

class Extractor(GPTClient):
    def __init__(self):
        super().__init__()
        self.parser = PydanticOutputParser(pydantic_object=UserPreferenceContext)

    async def extract_info(self, state):
        """
        사용자의 입력에서 정보를 추출하여 context를 업데이트합니다.
        """
        user_input = state.get("user_prompt", "")
        current_context = state.get("user_context", {})

        input_variables = {
            "user_input": user_input,
            "current_context": current_context,
            "format_instructions": self.parser.get_format_instructions()
        }

        try:
            return await self.run(
                prompt_name="extraction",
                input_variables=input_variables,
                parser=self.parser
            )
        except:
            return current_context