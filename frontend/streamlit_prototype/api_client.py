from typing import Any

def post_prewalk_init(payload: dict[str, Any]) -> dict[str, Any]:
    """
    /api/prewalk/init 호출 예정 함수.

    담당:
    - 앱 최초 진입 시 현재 위치와 user_id를 backend에 보낼 예정
    - backend가 반환한 session_id와 UIEvent 목록을 받을 예정

    금지:
    - 현재 단계에서는 requests/httpx 등 실제 HTTP 요청 구현 금지
    """
    pass

def post_prewalk_message(payload: dict[str, Any]) -> dict[str, Any]:
    """
    /api/prewalk/message 호출 예정 함수.

    담당:
    - 사용자 채팅 메시지를 backend에 보낼 예정
    - backend가 반환한 UIEvent 목록을 받을 예정

    금지:
    - 현재 단계에서는 실제 HTTP 요청 구현 금지
    """
    pass

def post_route_recommend(payload: dict[str, Any]) -> dict[str, Any]:
    """
    /api/routes/recommend 호출 예정 함수.

    담당:
    - 명시적 경로 추천 요청을 backend에 보낼 예정
    - backend가 반환한 RouteResult 또는 UIEvent 목록을 받을 예정

    금지:
    - 현재 단계에서는 실제 HTTP 요청 구현 금지
    """
    pass
