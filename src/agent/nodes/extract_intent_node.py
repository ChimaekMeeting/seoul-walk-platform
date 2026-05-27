from typing import Any

def extract_intent(state: dict[str, Any]) -> dict[str, Any]:
    """
    사용자 자연어 메시지에서 mode, distance, destination, preference, profile 후보를 추출한다.

    금지:
    - 현재 단계에서 실제 LLM 호출 금지
    - prompt 직접 실행 금지
    """
    pass
