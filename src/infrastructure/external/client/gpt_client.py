from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI
from langchain_core.prompts import load_prompt
from openai import AsyncOpenAI
from typing import Optional, Any

load_dotenv()

class GPTClient:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=os.getenv("OPENAI_API_KEY"),
            model="gpt-4o-mini",
            temperature=0.1
        )
        # 이미지 생성(Images API)은 Chat Completions(ChatOpenAI)와 별개 경로라 전용 클라이언트를 둔다.
        self.image_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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

    async def generate_image(
        self,
        prompt_name,
        input_variables,
        model: str = "gpt-image-1",
        size: str = "1024x1024",
    ) -> str:
        """
        .yaml 프롬프트를 렌더링해 OpenAI Images API로 이미지를 생성하고 base64 인코딩된 이미지 데이터를 반환합니다.
        get_response()와 달리 Chat Completions가 아닌 별도 엔드포인트를 호출한다.
        """
        prompt_template = load_prompt(path=f"src/prompt/{prompt_name}.yaml", encoding="utf-8")
        prompt = prompt_template.format(**input_variables)

        response = await self.image_client.images.generate(
            model=model,
            prompt=prompt,
            size=size,
        )
        return response.data[0].b64_json