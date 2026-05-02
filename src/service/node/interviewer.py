from dotenv import load_dotenv
import os
from langchain_core.output_parsers import (
    JsonOutputParser,
    StrOutputParser
)
from langchain_core.prompts import PromptTemplate

from src.client.gpt_client import GPTClient

load_dotenv()

class Interviewer(GPTClient):
    def __init__(self):
        super().__init__()

        self.json_parser = JsonOutputParser()
        self.str_parser = StrOutputParser()

        self.prompt_file_name = "prompt_file"

    def save_prompt(self, content):
        """
        생성된 프롬프트 내용을 .md 파일로 저장합니다.
        """
        path = f"src/prompt/{self.prompt_file_name}.md"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("-" * 50 + "\n")
                f.write(content)
                f.write("\n" + "=" * 50 + "\n")
        except Exception as e:
            print(e)

    async def create_prompt(self, state):
        """
        state 정보를 분석하여 맞춤형 PromptTemplate 객체를 생성하고 반환합니다.
        """
        user_context = state.get("user_context", {})
        user_prompt = state.get("user_prompt", "")
        missing_info = [k for k, v in user_context.items() if v is None]

        if not missing_info:
            instruction = (
                "모든 정보가 수집되었습니다. 수집된 정보를 요약해 보여주고 "
                "최종적으로 산책로 생성을 시작할지 확인받으세요."
            )
        else:
            instruction = f"현재 사용자로부터 '{missing_info}' 정보를 알아내야 합니다. 자연스럽게 질문을 이어가세요."

        template_text = await self.run(
            prompt_name="prompt_creation",
            input_variables={
                "current_context": str(user_context).replace("{", "{{").replace("}", "}}"),
                "format_instructions": instruction,
                "user_input": user_prompt
            },
            parser=self.str_parser
        )
        
        self.save_prompt(template_text)
        return PromptTemplate(
            input_variables=["user_input"],
            template=template_text
        )

    async def get_response(self, state):
        """
        .yaml 프롬프트를 기반으로 GPT가 생성한 응답을 반환합니다.
        """
        prompt_template = await self.create_prompt(state)

        chain = prompt_template | self.llm | self.str_parser
        response = await chain.ainvoke({"user_input": state.get("user_prompt", "")})

        missing_info = [k for k, v in state.get("user_context", {}).items() if v is None]
        state["next_node"] = "end" if not missing_info else "interview"
            
        return response, state