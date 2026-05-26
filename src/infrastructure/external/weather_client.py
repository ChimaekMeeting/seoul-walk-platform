from typing import Any

def fetch_weather_raw(lat: float, lon: float) -> dict[str, Any]:
    """
    외부 날씨 API raw data 조회 예정 함수.
    raw data는 context/weather_context.py에서 표준화된다.

    금지:
    - 현재 단계에서 실제 HTTP 호출 구현 금지
    - 날씨 provider의 raw field를 application/domain에 직접 노출 금지

    TODO:
    - 기상청/기타 provider 중 어떤 raw format을 우선 지원할지 정한다.
    - cache TTL 정책을 cache 계층과 맞춘다.
    """
    pass

def fetch_air_quality_raw(lat: float, lon: float) -> dict[str, Any]:
    """
    외부 미세먼지/대기질 API raw data 조회 예정 함수.
    raw data는 context/air_quality_context.py에서 표준화된다.

    금지:
    - 현재 단계에서 실제 HTTP 호출 구현 금지
    - 대기질 provider의 raw field를 application/domain에 직접 노출 금지

    TODO:
    - 미세먼지/초미세먼지 단위와 등급 기준을 context 계층과 맞춘다.
    """
    pass
