from typing import Any

def get_weather_context(lat: float, lon: float) -> dict[str, Any]:
    """
    날씨/미세먼지 context를 가져오는 agent tool 예정 함수.

    예정 흐름:
    1. infrastructure/external/weather_client로 raw data 조회
    2. context/weather_context, context/air_quality_context로 표준화
    3. 표준 context 반환

    현재 단계에서는 실제 호출 구현 금지.
    """
    pass
