from langchain_core.output_parsers import JsonOutputParser

class MapSelector:
    def __init__(self, gpt_client):
        self.gpt_client = gpt_client
        self.output_parser = JsonOutputParser()

        self.function_map = {
            # 추후 작성해두겠습니다.
        }

    async def get_response(self, context: dict):
        """
        사용자의 요구사항에 적합한 길찾기 알고리즘을 사용하기 위해 function calling을 진행합니다.
        """
        return await self.gpt_client.get_response(
            prompt_name="map_selection",
            input_data={
                "context": context,
                "format_instructions": self.parser.get_format_instructions()
            },
            output_parser=self.parser
        )
    
    async def run(self, context: dict):
        """
        사용자의 요구사항에 적합한 길찾기 알고리즘을 호출합니다.
        """
        # response.keys() = ["function", "query"]
        response = await self.get_response(context)
        function = self.function_map(response.get("function"))
        query = self.function_map(response.get("query"))

        # function(query)
