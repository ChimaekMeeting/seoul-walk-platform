from typing import Any

class AirQualityContext:
    """
    대기질 상황을 표준화한 Context 데이터 계약.

    필드:
    - pm10: 미세먼지 수치
    - pm25: 초미세먼지 수치
    - air_status: 좋음/보통/나쁨 등 요약 상태
    - caution_level: none/caution/warning 등 산책 주의 수준
    - walk_message_seed: 에이전트가 안내 문구를 만들 때 참고할 구조화 데이터
    - raw: optional. 디버깅/추적용 원본 데이터

    TODO:
    - air_status와 caution_level 허용값을 확정한다.
    - 국내 대기질 기준표와 mapping 정책을 정한다.
    """
    pm10: float | None
    pm25: float | None
    air_status: str | None
    caution_level: str | None
    walk_message_seed: dict[str, Any]
    raw: dict[str, Any] | None

    pass

def create_air_quality_context(raw_air: dict[str, Any]) -> dict[str, Any]:
    """
    외부 API에서 가져온 raw 미세먼지 데이터를 서비스 내부 규격으로 포장한다.

    담당:
    - 미세먼지 수치, 등급 판단
    - 산책 주의/경고 여부 플래그 생성

    금지:
    - 실제 에어코리아 API 통신 등 호출 금지

    TODO:
    - raw_air provider별 field mapping을 정한다.
    - weather_context와 합쳐질 때 중복 메시지 정책을 정한다.
    """
    pass
