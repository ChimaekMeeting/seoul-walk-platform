from langchain_core.output_parsers import (
    JsonOutputParser,
    StrOutputParser
)
from langchain_core.prompts import PromptTemplate, load_prompt
from typing import Tuple

from src.infrastructure.external.client.gpt_client import GPTClient
from src.agent.tools.place_tool import PlaceTool
from src.agent.utils.chatbot_utils import PromptUtils
from src.schema.prewalk_schema import (
    DestinationPreference,
    DistancePreference,
    State,
    Location
)

class StateManager:
    @staticmethod
    def get_missing_info(user_context):
        """
        산책 경로 추천을 위해 필요한 항목 중 어떤 항목을 더 채워야하는지 확인합니다.
        """
        missing = []
        if not user_context:
            return ["산책 모드 설정"]

        if not user_context.origin or not user_context.origin.lat:
            missing.append("출발지 상세 위치")

        if isinstance(user_context, DestinationPreference):
            if not user_context.destination or not user_context.destination.lat:
                missing.append("목적지 상세 위치")

        if isinstance(user_context, DistancePreference):
            if not user_context.distance_km:
                missing.append("산책 거리")

        if not user_context.purpose:
            missing.append("산책 목적")

        return missing

    def is_complete(self, user_context):
        """
        산책 경로 추천을 위해 필요한 항목이 모두 채워졌는지 확인합니다.
        """
        missing_info = self.get_missing_info(user_context)
        return len(missing_info) == 0, missing_info

class Interviewer(GPTClient):
    def __init__(self):
        super().__init__()

        self.state_manager = StateManager()
        self.place_tool = PlaceTool()
        self.prompt_utils = PromptUtils()

        self.model = self.llm.bind_tools(self.place_tool.tools)

        self.json_parser = JsonOutputParser()
        self.str_parser = StrOutputParser()

    def get_instruction(self, is_complete, missing_info, current_location):
        location_context = f"현재 사용자의 위치 정보는 다음과 같습니다: {current_location}"

        if is_complete:
            instruction = (
                "모든 필수 정보(출발지/목적지 좌표, 거리, 순환 여부)가 완벽하게 수집되었습니다!\n"
                "더 이상 질문하거나 Kakao 도구를 호출하지 마세요.\n"
                "지금까지 수집된 정보를 바탕으로 '산책 티켓'을 발행하듯 예쁘게 요약하고, "
                "최종적으로 산책로 생성을 시작할지 사용자에게 확답을 받으세요."
            )
        else:
            tool_instruction = (
                "사용자가 장소를 언급했지만 좌표(lat, lon)가 null이라면 반드시 Kakao 도구를 호출하세요.\n"
                "출발지라면 target='origin', 목적지라면 target='destination'으로 명시해야 합니다."
            )
            instruction = f"현재 사용자로부터 '{missing_info}' 정보를 알아내야 합니다. 자연스럽게 질문을 이어가세요."
            instruction = f"{tool_instruction}\n{instruction}"

        format_rule = "반드시 생성하는 프롬프트 내에 사용자의 입력을 받는 '{user_input}' 변수를 포함시켜야 합니다."
        return f"{location_context}\n{instruction}\n{format_rule}"

    async def create_prompt(self, state: State, is_complete, missing_info):
        """
        state 정보를 분석하여 맞춤형 PromptTemplate 객체를 생성하고 반환합니다.
        """
        user_context = state.user_context
        current_location = state.current_location

        raw_template_text = load_prompt("src/prompt/interview.yaml", encoding="utf-8")
        formatted_text = raw_template_text.format(
            current_context=self.prompt_utils.format_for_prompt(user_context),
            format_instructions=self.get_instruction(is_complete, missing_info, self.prompt_utils.format_for_prompt(current_location)),
            user_input="{user_input}"
        )

        return PromptTemplate(
            input_variables=["user_input"],
            template=formatted_text
        )

    async def _execute_tool_calls(self, tool_calls: list) -> tuple[list, dict]:
        results = []
        candidates = {}

        for call in tool_calls:
            name, args = call["name"], call["args"]
            target = args.get("target", "destination")
            output = await self.place_tool.tool_map[name].ainvoke(args)

            if "documents" in output:
                candidates[f"{target}_candidate"] = [
                    Location(
                        lat=float(d["y"]),
                        lon=float(d["x"]),
                        address=d["address_name"],
                        place_name=d["place_name"],
                    )
                    for d in output["documents"]
                ]
            results.append({"tool": name, "result": output})

        return results, candidates

    async def run(self, state: State) -> Tuple[str, State]:
        """
        .yaml 프롬프트를 기반으로 GPT가 생성한 응답을 반환합니다.
        """
        is_complete, missing_info = self.state_manager.is_complete(state.user_context)

        prompt_template = await self.create_prompt(state, is_complete, missing_info)

        chain = prompt_template | self.model
        raw_response = await chain.ainvoke({"user_input": state.user_prompt})

        if raw_response.tool_calls:
            tool_results, candidates = await self._execute_tool_calls(raw_response.tool_calls)

            if "origin_candidate" in candidates:
                state.origin_candidate = candidates["origin_candidate"]
            if "destination_candidate" in candidates:
                state.destination_candidate = candidates["destination_candidate"]

            response = await super().get_response(
                prompt_name="location_formatter",
                input_variables={
                    "tool_calls": str(tool_results),
                    "user_input": state.user_prompt,
                    "current_location": self.prompt_utils.format_for_prompt(state.current_location)
                },
                parser=self.str_parser
            )
        else:
            response = raw_response.content

        state.next_node = "end" if is_complete else "interview"

        return response, state