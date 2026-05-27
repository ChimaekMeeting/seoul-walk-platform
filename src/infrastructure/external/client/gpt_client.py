from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import load_prompt
from typing import Optional, Any

load_dotenv()

class GPTClient:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            model="gpt-4o-mini",
            temperature=0.1
        )

    async def get_response(
        self,
        prompt_name,
        input_variables,
        parser: Optional[Any] = None,
        llm: Optional[Any] = None
    ):
        """
        .yaml 프롬프트를 기반으로 GPT가 생성한 응답을 반환합니다.
        """
        prompt_template = load_prompt(path=f"src/prompt/{prompt_name}.yaml", encoding="utf-8")
        
        target_llm = llm if llm else self.llm

        if parser:
            chain = prompt_template | target_llm | parser
        else:
            chain = prompt_template | target_llm
        
        return await chain.ainvoke(input_variables)