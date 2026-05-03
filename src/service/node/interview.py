from langchain_core.output_parsers import (
    JsonOutputParser,
    StrOutputParser
)
from langchain_core.prompts import PromptTemplate, load_prompt

from src.client.gpt_client import GPTClient
from src.client.kakao_client import KakaoClient

class Interviewer(GPTClient):
    def __init__(self, kakao_client: KakaoClient):
        super().__init__()

        self.kakao_client = kakao_client
        self.tools = [
            self.kakao_client.get_address_from_category,
            self.kakao_client.get_address_from_coords,
            self.kakao_client.get_address_from_keyword
        ]
        # tool 바인딩
        self.llm_with_tools = self.llm.bind_tools(self.tools)

        self.json_parser = JsonOutputParser()
        self.str_parser = StrOutputParser()

    def get_instruction(self, is_complete, missing_info, current_location):
        location_context = f"현재 사용자의 위치 정보는 다음과 같습니다: {current_location}"
    
        if is_complete:
            # 데이터가 물리적으로 모두(좌표 포함) 채워진 경우
            instruction = (
                "모든 필수 정보(출발지/목적지 좌표, 거리, 순환 여부)가 완벽하게 수집되었습니다!\n"
                "더 이상 질문하거나 Kakao 도구를 호출하지 마세요.\n"
                "지금까지 수집된 정보를 바탕으로 '산책 티켓'을 발행하듯 예쁘게 요약하고, "
                "최종적으로 산책로 생성을 시작할지 사용자에게 확답을 받으세요."
            )
        else:
            # 데이터가 부족한 경우
            tool_instruction = (
                "사용자가 장소를 언급했지만 좌표(lat, lon)가 null이라면 반드시 Kakao 도구를 호출하세요.\n"
                "출발지라면 target='origin', 목적지라면 target='destination'으로 명시해야 합니다."
            )
            instruction = f"현재 사용자로부터 '{missing_info}' 정보를 알아내야 합니다. 자연스럽게 질문을 이어가세요."
            instruction = f"{tool_instruction}\n{instruction}"

        format_rule = "반드시 생성하는 프롬프트 내에 사용자의 입력을 받는 '{user_input}' 변수를 포함시켜야 합니다."
        return f"{location_context}\n{instruction}\n{format_rule}"
    
    async def create_prompt(self, state):
        """
        state 정보를 분석하여 맞춤형 PromptTemplate 객체를 생성하고 반환합니다.
        """
        user_context = state.get("user_context", {})
        current_location = state.get("current_location", {})

        is_complete = self.check_is_complete(state)

        origin = user_context.get("origin") or {}
        destination = user_context.get("destination") or {}
        is_circular = user_context.get("is_circular")

        # 구체적으로 어떤 정보가 비었는지 리스트업
        missing_info = []
    
        # lat 정보가 없는지 체크 (origin이 None이어도 이제 에러가 나지 않음)
        if not origin.get("lat"): 
            missing_info.append("출발지 상세 위치")
    
        if is_circular is None: 
            missing_info.append("순환 여부")
    
        # 편도(False)인데 목적지 좌표가 없는 경우
        if is_circular is False and not destination.get("lat"):
            missing_info.append("목적지 상세 위치")
        
        if not user_context.get("distance_km"): 
            missing_info.append("산책 거리")

        raw_template_text = load_prompt("src/prompt/interview.yaml", encoding="utf-8")

        safe_context = str(user_context).replace("{", "{{").replace("}", "}}")
        safe_location = str(current_location).replace("{", "{{").replace("}", "}}")

        formatted_text = raw_template_text.format(
            current_context=safe_context,
            format_instructions=self.get_instruction(is_complete, missing_info, safe_location),
            user_input="{user_input}" 
        )

        return PromptTemplate(
            input_variables=["user_input"],
            template=formatted_text
        )
    
    def check_is_complete(self, state):
        user_context = state.get("user_context", {})
        is_circular = user_context.get("is_circular")
        origin = user_context.get("origin")
        destination = user_context.get("destination")

        def is_valid_location(loc):
            """내용물이 비어있지 않은 유효한 Location 객체인지 확인"""
            if not isinstance(loc, dict):
                return False
            # 필수 키들이 존재하고, 그 값이 None이나 빈 문자열이 아닌지 검사
            required_keys = ["place_name", "address", "lat", "lon"]
            return all(loc.get(key) not in [None, ""] for key in required_keys)

        # 1. 출발지(origin)는 공통 필수 사항
        if not is_valid_location(origin):
            return False

        # 2. 순환(True)인 경우: 출발지만 유효하면 즉시 종료 가능
        if is_circular is True:
            return True

        # 3. 편도(False)인 경우: 목적지(destination)까지 유효해야 종료 가능
        if is_circular is False:
            return is_valid_location(destination)

        # 4. is_circular가 결정되지 않았거나(None), 위 조건들을 만족하지 못하면 계속 진행
        return False

    async def run(self, state):
        """
        .yaml 프롬프트를 기반으로 GPT가 생성한 응답을 반환합니다.
        """
        prompt_template = await self.create_prompt(state)

        chain = prompt_template | self.llm_with_tools
        raw_response = await chain.ainvoke({"user_input": state.get("user_prompt", "")})

        if raw_response.tool_calls:
            tool_outputs = []
            for tool_call in raw_response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]

                target = tool_args.get("target", "destination")

                tool_func = getattr(self.kakao_client, tool_name)
                output = await tool_func.ainvoke(tool_args)

                if "documents" in output:
                    candidates = [
                        {
                            "place_name": doc["place_name"],
                            "address": doc["address_name"],
                            "lat": float(doc["y"]),
                            "lon": float(doc["x"])
                        } for doc in output["documents"]
                    ]
                    state[f"{target}_candidate"] = candidates

                tool_outputs.append({
                    "tool": tool_name,
                    "query": tool_args.get("keyword") or tool_args.get("category"),
                    "result": output
                })

            response = await super().get_response(
                prompt_name="location_formatter", # 검색 결과를 문장으로 다듬어주는 별도 yaml 필요
                input_variables={
                    "tool_calls": str(tool_outputs),
                    "user_input": state.get("user_prompt", ""),
                    "current_location": state.get("current_location")
                },
                parser=self.str_parser
            )
        else:
            response = raw_response.content

        if self.check_is_complete(state):
            state["next_node"] = "end"
        else:
            state["next_node"] = "interview"

        return response, state