from typing import Any

def get_weather_context(request: dict[str, Any]) -> dict[str, Any]:
    """
    현재 위치 기준 날씨/미세먼지 context 조회 API 계약.

    예상 요청:
    - lat
    - lon

    예정 흐름:
    - application 또는 agent tool을 통해 weather context 반환

    금지:
    - 실제 weather API 호출 구현 금지
    - 현재 단계에서 실제 application/agent 호출 구현 금지
    """
    pass
