from langchain_core.output_parsers import PydanticOutputParser
from src.client.gpt_client import GPTClient
from src.schema.prewalk_schema import Weights
from src.service.prewalk.chatbot_utils import PromptUtils

class WeightAssigner(GPTClient):
    def __init__(self):
        super().__init__()

        self.prompt_utils = PromptUtils()
        self.parser = PydanticOutputParser(pydantic_object=Weights)

    async def run(self, state) -> dict:
        """
        사용자의 산책 목적과 상황에 기반하여 feature별 가중치를 결정합니다.
        """
        user_context = state.get("user_context")
        weather_data = state.get("weather_data")

        is_circular = user_context.get("is_circular")
        origin = user_context.get("origin")
        destination = origin if is_circular else user_context.get("destination")

        return await super().get_response(
            prompt_name="weight_assign",
            input_variables={
                "is_circular": "순환" if is_circular else "편도",
                "origin": self.prompt_utils.format_for_prompt(origin),
                "destination": self.prompt_utils.format_for_prompt(destination),
                "purpose": user_context.get("purpose"),
                "weather_data": self.prompt_utils.format_for_prompt(weather_data),
                "format_instructions": self.parser.get_format_instructions()
            },
            parser=self.parser
        )