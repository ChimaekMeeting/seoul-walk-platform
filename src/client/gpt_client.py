from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import load_prompt

load_dotenv()

class GPTClient:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=os.getenv("OPENAI_API"),
            model="gpt-4o-mini",
            temperature=0.7
        )

    async def get_response(self, prompt_name, input_variables, parser):
        """
        .yaml 프롬프트를 기반으로 GPT가 생성한 응답을 반환합니다.
        """
        prompt_template = load_prompt(path=f"src/prompt/{prompt_name}.yaml", encoding="utf-8")

        chain = prompt_template | self.llm | parser
        
        return await chain.ainvoke(input_variables)