from langchain_core.output_parsers import JsonOutputParser

class MapSelector:
    def __init__(self, gpt_client):
        self.gpt_client = gpt_client
        self.output_parser = JsonOutputParser()

        self.function_map = {
            # 추후 작성해두겠습니다.
        }

    async def get_response(self, context: dict, weights: dict):
        """
        사용자의 요구사항에 적합한 길찾기 알고리즘을 사용하기 위해 function calling을 진행합니다.
        """
        return await self.gpt_client.get_response(
            prompt_name="map_selection",
            input_data={
                "context": context,
                "weights": weights,
                "format_instructions": self.parser.get_format_instructions()
            },
            output_parser=self.parser
        )
    
    async def run(self, context: dict, weights: dict):
        """
        사용자의 요구사항에 적합한 길찾기 알고리즘을 호출합니다.
        params:
          - context: 순환 여부, 출발지, 목적지, 산책 목적
          context = {
            "is_circular": None,        # 순환 여부 (True: 순환, False: 편도)
            "origin": None,             # 출발지
            "destination": None,        # 목적지
            "purpose": None             # 산책 목적
          },
          - weights: 지도 레이어별 가중치 레이어
          weights
        """
        response = await self.get_response(context, weights)
        function = self.function_map(response.get("function"))
        query = self.function_map(response.get("query"))

        return function, query
