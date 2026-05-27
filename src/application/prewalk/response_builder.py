from typing import Any, Optional

def build_initial_response(context: dict[str, Any]) -> list[Any]:
    """
    초기 진입 context를 바탕으로 초기 인사말 및 화면(UIEvent 목록)을 빌드한다.
    """
    pass

def build_chat_response(intent: dict[str, Any], route_result: Optional[Any] = None) -> list[Any]:
    """
    사용자 의도 분석 결과와 (라우팅을 수행했다면) 탐색 결과를 바탕으로
    에이전트 답변 및 화면(UIEvent 목록)을 빌드한다.
    """
    pass
