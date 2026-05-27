from typing import Any

def run_walk_agent(input_state: dict[str, Any]) -> dict[str, Any]:
    """
    산책 추천 Agent workflow의 단일 진입점.

    예정 흐름:
    1. extract_intent_node 호출
    2. fetch_context_node 호출
    3. recommend_route_node 호출
    4. build_response_node 호출

    현재 단계에서는 실제 LangGraph/LangChain 구현 금지.
    """
    pass
