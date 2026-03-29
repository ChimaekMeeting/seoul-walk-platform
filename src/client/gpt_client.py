from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import load_prompt

load_dotenv()
OPENAI_API = os.getenv("OPENAI_API")

class GPTClient:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=OPENAI_API,
            model="gpt-4o-mini",
            temperature=0.7
        )

    async def get_response(self, prompt_name, input_data, output_parser):
        """
        .yaml 프롬프트를 기반으로 GPT가 생성한 응답을 반환합니다.
        """
        prompt_path = os.path.join("src", "prompt", f"{prompt_name}.yaml")
        prompt_template = load_prompt(prompt_path, encoding="utf-8")

        chain = prompt_template | self.llm | output_parser
        
        return await chain.ainvoke(input_data)
    
    # 37.6346, 126.8328
