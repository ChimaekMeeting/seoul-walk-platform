from langchain_core.output_parsers import PydanticOutputParser
from src.infrastructure.external.client.gpt_client import GPTClient
from src.schema.prewalk_schema import Weights, State
from src.service.prewalk.chatbot_utils import PromptUtils, PydanticUtils

class WeightAssigner(GPTClient):
    def __init__(self):
        super().__init__()

        self.prompt_utils = PromptUtils()
        self.parser = PydanticOutputParser(pydantic_object=Weights)

    async def run(self, state: State) -> dict:
        """
        사용자의 산책 목적과 상황에 기반하여 feature별 가중치를 결정합니다.
        """
        user_context = state.user_context
        context_dict = PydanticUtils.dump(user_context)

        context_summary = "\n".join([
            f"- {key}: {self.prompt_utils.format_for_prompt(value)}"
            for key, value in context_dict.items()
        ])

        input_variables = {
            "walk_mode": getattr(user_context, "mode", "Unknown"), # 현재 어떤 모드인지 명시
            "context_summary": context_summary,
            "weather_data": self.prompt_utils.format_for_prompt(state.weather_data),
            "format_instructions": self.parser.get_format_instructions(),
        }
        print(input_variables)

        return await super().get_response(
            prompt_name="weight_assign",
            input_variables=input_variables,
            parser=self.parser
        )