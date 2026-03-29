from langchain_core.output_parsers import StrOutputParser

class Interviewer:
    def __init__(self, gpt_client):
        self.gpt_client = gpt_client
        self.parser = StrOutputParser()
    
    async def run(self, context: dict) -> str:
        """
        부족한 정보를 파악하여 사용자에게 던질 자연스러운 질문을 생성합니다.
        """
        question = await self.gpt_client.get_response(
            prompt_name="interview",
            input_data={
                "context": context,
            },
            output_parser=self.parser
        )

        return question