from typing import Any

def init_prewalk_session(request: dict[str, Any]) -> dict[str, Any]:
    """
    앱 최초 진입 시 호출될 예정인 API endpoint 계약.

    예상 요청:
    - user_id
    - current_location
    - client_type: streamlit | react_native
    - locale/timezone

    예정 흐름:
    1. application/prewalk.start_prewalk_session 호출
    2. weather/location context 준비
    3. 초기 UIEvent 목록 반환

    반환 예정:
    {
        "session_id": str,
        "events": list[UIEvent]
    }

    금지:
    - 현재 단계에서 FastAPI decorator 구현 금지
    - 실제 application 호출 구현 금지
    """
    pass

def send_prewalk_message(request: dict[str, Any]) -> dict[str, Any]:
    """
    사용자가 채팅 메시지를 보냈을 때 호출될 예정인 API endpoint 계약.

    예상 요청:
    - session_id
    - message
    - current_location

    반환 예정:
    {
        "session_id": str,
        "events": list[UIEvent]
    }

    금지:
    - 현재 단계에서 FastAPI decorator 구현 금지
    - 실제 agent/application 호출 구현 금지
    """
    pass
