from typing import Any, Optional

def extract_route_intent(message: str, context: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    사용자의 자연어 메시지를 분석하여 Route Engine이 이해할 수 있는 Intent/Profile 후보로 변환한다.

    담당:
    - 메시지 분석 파이프라인 호출

    금지:
    - LLM/GPT API 통신 로직 직접 구현 금지 (추후 Agent/Infra 계층에 위임)
    """
    pass
