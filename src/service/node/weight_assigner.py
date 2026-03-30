from langchain_core.output_parsers import JsonOutputParser

class WeightAssigner:
    def __init__(self, gpt_client):
        self.gpt_client = gpt_client
        self.parser = JsonOutputParser()

    async def run(self, context: dict, weather_data: dict) -> dict:
        """
        사용자의 산책 목적과 상황에 기반하여 feature별 가중치를 결정합니다.
        """
        is_circular = context.get("is_circular")
        origin = context.get("origin")
        destination = origin if is_circular else context.get("destination")

        weights = await self.gpt_client.get_response(
            prompt_name="weight_assign",
            input_data={
                "is_circular": "순환" if is_circular else "편도",
                "origin": origin,
                "destination": destination,
                "purpose": context.get("purpose"),
                "weather_data": weather_data,
                "format_instructions": self.parser.get_format_instructions()
            },
            output_parser=self.parser
        )

        return weights