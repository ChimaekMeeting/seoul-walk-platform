from typing import Any

def preview_ui_events(request: dict[str, Any]) -> dict[str, Any]:
    """
    개발/검증용 UIEvent preview API 계약.

    목적:
    - Streamlit prototype 또는 React Native 개발 중 UIEvent payload 렌더링을 검증하기 위함

    예상 요청:
    - events
    - client_type

    금지:
    - 실제 UI 렌더링 구현 금지
    - 현재 단계에서 FastAPI decorator 구현 금지
    """
    pass
