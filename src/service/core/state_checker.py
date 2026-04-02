from src.repository.chat_state_repository import ChatStateRepository
from typing import Dict, Any
from src.service.node.extractor import Extractor
from src.service.router.plan_router import PlanRouter
from src.service.router.location_router import LocationRouter

class StateChecker:
    def __init__(self, gpt_client, string_converter):
        self.gpt_client = gpt_client
        self.extractor = Extractor(gpt_client)
        self.plan_router = PlanRouter(gpt_client)
        self.location_router = LocationRouter(gpt_client, string_converter)

    def is_context_complete(self, context: Dict[str, Any]) -> bool:
        """
        필수 필드(순환 여부, 출발지, 목적지, 목적)가 채워졌는지 검사합니다.
        """
        # 순환 여부가 결정되지 않았으면 False
        if context.get("is_circular") is None:
            return False
        
        # 순환이라면 출발지, 산책 목적이 무조건 있어야 함
        if context.get("is_circular"):
            if context.get("origin") and context.get("purpose"):
                return True
            return False
        
        # 편도라면 출발지, 목적지, 산책 목적이 무조건 있어야 함
        if context.get("is_circular") is False:
            if context.get("origin") and context.get("destination") and context.get("purpose"):
                return True
            return False
        
        return False
    
    def is_location_ok(self, data):
        """
        """
        for value in data.values():
            if isinstance(value, dict):
                if None in value.values():
                    return False
                for v in value:
                    if isinstance(v, str) and "" == v:
                        return False
            
            elif isinstance(value, str) and  "" == value:
                    return False
                
        if not data.get("is_location_selected") or not data.get("is_in_candidates"):
            return False
        
        return True
    
    async def handle_location_routing(self, user_prompt, context, state):
        """
        """

        origin_res, destination_res = await self.location_router.run(
            user_prompt,
            context,
            state.get("origin_candidate"),
            state.get("destination_candidate")
        )

        print("출발지")
        print(origin_res)

        print("목적지")
        print(destination_res)

        context_update = origin_res.get("context_update")
        is_circular = context_update.get("is_circular")
        state["user_context"]["is_circular"] = is_circular
        state["user_context"]["purpose"] = context_update.get("purpose")

        origin_ok = self.is_location_ok(origin_res)
        destination_ok = self.is_location_ok(destination_res)
        print("\n테스트")
        print(is_circular)
        print(origin_ok)
        print(destination_ok)

        # 순환
        if is_circular:
            # CASE 1: 출발지가 후보군 내에서 명확히 확정된 경우
            if origin_ok:
                location_data = {
                    "place_name": origin_res.get("place_name"),
                    "address": origin_res.get("address"),
                    "coordinate": origin_res.get("coordinate")
                }
                state["user_context"]["origin"] = location_data
                state["user_context"]["destination"] = location_data
            # CASE 2: 유저가 새로운 장소를 언급했거나 후보 외의 장소를 선택한 경우
            elif not origin_res.get("is_in_candidates"):
                state["user_context"]["origin"] = origin_res.get("place_name")
                state["user_context"]["destination"] = origin_res.get("place_name")

            if origin_ok:
                state["next_node"] = "plan_summarization"
            else:
                state["next_node"] = "location_selection"
        # 편도
        else:
            if origin_ok:
                state["user_context"]["origin"] = {
                    "place_name": origin_res.get("place_name"),
                    "address": origin_res.get("address"),
                    "coordinate": origin_res.get("coordinate")
                }
            elif origin_res.get("is_in_candidates"):
                state["user_context"]["origin"] = origin_res.get("place_name")

            if destination_ok:
                state["user_context"]["destination"] = {
                    "place_name": destination_res.get("place_name"),
                    "address": destination_res.get("address"),
                    "coordinate": destination_res.get("coordinate")
                }
            elif not destination_res.get("is_in_candidates"):
                state["user_context"]["destination"] = destination_res.get("place_name")

            if origin_ok and destination_ok:
                state["next_node"] = "plan_summarization"
            else:
                state["next_node"] = "location_selection"

        print(state["next_node"])
        print()

        return state


    async def handle_plan_routing(self, user_prompt, state):
        """
        """
        is_positive = await self.plan_router.run(user_prompt)

        # 확정O -> feature별 가중치 결정
        if is_positive:
            state["is_confirmed"] = True
            state["next_node"] = "weighting"
        # 확정X -> 정보 추출 반복
        else:
            state["is_confirmed"] = False
            state["next_node"] = "extraction"

        return is_positive, state
    
    async def extract_and_validate_context(self, user_prompt, state):
        """
        """
        # 정보 추출
        state["user_prompt"] = user_prompt

        extracted_context = await self.extractor.run(
            user_prompt=user_prompt,
            context=state["user_context"]
        )

        # 상태 업데이트
        state["user_context"].update(extracted_context)

        # 필수 정보가 다 모였는지 확인
        if self.is_context_complete(state["user_context"]):
            state["next_node"] = "location_selection"
        else:
            state["next_node"] = "interview"

        return state
    
    async def update_and_check(self, thread_id: str, user_prompt: str) -> Dict[str, Any]:
        """
        사용자 프롬프트를 분석하여 상태를 업데이트하고, 다음 단계를 결정합니다.
        """
        # 현재 상태 로드
        state = await ChatStateRepository.get_state(thread_id)
        next_node = state.get("next_node")
        context = state.get("user_context")

        # 출발지, 목적지 확정 판정 노드 실행
        if next_node == "location_routing":
            return await self.handle_location_routing(user_prompt, context, state)

        # 산책 계획 확정 판정 노드 실행
        elif next_node == "plan_routing":
            is_positive, state = await self.handle_plan_routing(user_prompt, state)
            if is_positive:
                return state
        
        # 정보 추출 및 산책 필수 조건 충족 여부 확인
        return await self.extract_and_validate_context(user_prompt, state)