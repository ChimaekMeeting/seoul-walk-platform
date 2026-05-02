from dotenv import load_dotenv
import os
from langchain_openai import ChatOpenAI
from langchain_core.output_parsers import (
    JsonOutputParser,
    StrOutputParser,
    PydanticOutputParser
)
from langchain_core.prompts import load_prompt

from src.schema.prewalk_schema import UserPreferenceContext

load_dotenv()

class GPTClient:
    def __init__(self):
        self.llm = ChatOpenAI(
            api_key=os.getenv("OPENAI_API"),
            model="gpt-4o-mini",
            temperature=0.7
        )

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
        missing_info = [k for k, v in user_context.items() if v is None]

        if not missing_info:
            instruction = (
                "모든 정보가 수집되었습니다. 수집된 정보를 요약해 보여주고 "
                "최종적으로 산책로 생성을 시작할지 확인받으세요."
            )
        else:
            instruction = f"현재 사용자로부터 '{missing_info}' 정보를 알아내야 합니다. 자연스럽게 질문을 이어가세요."

        prompt_template = load_prompt("src/prompt/prompt_creation.yaml", encoding="utf-8")
        template_text = prompt_template.format(
            current_context=user_context,
            format_instructions=instruction,
            user_input=state.get("user_prompt", "")
        )
        
        self.save_prompt(template_text)
        return prompt_template

    async def get_response(self, state):
        """
        .yaml 프롬프트를 기반으로 GPT가 생성한 응답을 반환합니다.
        """
        prompt_template = await self.create_prompt(state)

        chain = prompt_template | self.llm | self.str_parser
        response = await chain.ainvoke({"user_input": state.get("user_prompt", "")})

        missing_info = [k for k, v in state.get("user_context", {}).items() if v is None]
        if not missing_info:
            state["next_node"] = "end"
        else:
            state["next_node"] = "interview"
            
        return response, state
    
    async def extract_info(self, state):
        """
        사용자의 입력에서 정보를 추출하여 context를 업데이트합니다.
        """
        user_input = state.get("user_prompt", "")
        current_context = state.get("user_context", {})

        parser = PydanticOutputParser(pydantic_object=UserPreferenceContext)
        prompt_template = load_prompt(path="src/prompt/extraction.yaml", encoding="utf-8")

        chain = prompt_template | self.llm | parser

        try:
            return await chain.ainvoke({
                "user_input": user_input,
                "current_context": current_context,
                "format_instructions": parser.get_format_instructions()
            })
        except:
            return current_context