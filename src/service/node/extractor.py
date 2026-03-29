from src.schema.prewalk_schema import UserPreferenceContext
from langchain_core.output_parsers import JsonOutputParser

class Extractor:
    def __init__(self, gpt_client):
        self.gpt_client = gpt_client
        self.parser = JsonOutputParser(pydantic_object=UserPreferenceContext)

    async def run(self, user_prompt: str, context: dict) -> dict:
        """
        사용자 프롬프트에서 산책 조건을 추출하여 기존 컨텍스트와 병합합니다.
        """
        extracted_data = await self.gpt_client.get_response(
            prompt_name="extraction",
            input_data={
                "user_prompt": user_prompt,
                "context": context,
                "format_instructions": self.parser.get_format_instructions()
            },
            output_parser=self.parser
        )

        print("\nextraction")
        print(extracted_data)
        return extracted_data