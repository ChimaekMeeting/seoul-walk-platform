from typing import Any, Optional

class StreamlitPrototypeState:
    """
    미래 Streamlit prototype의 화면 상태 계약.

    필드:
    - session_id
    - current_location
    - messages
    - ui_events
    - selected_route
    - map_state

    금지:
    - 현재 단계에서 streamlit.session_state 직접 사용 금지
    """
    session_id: Optional[str]
    current_location: Optional[dict[str, float]]
    messages: list[dict[str, Any]]
    ui_events: list[dict[str, Any]]
    selected_route: Optional[dict[str, Any]]
    map_state: dict[str, Any]
    pass
