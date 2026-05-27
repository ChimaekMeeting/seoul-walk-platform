from typing import Any

class WeatherContext:
    """
    날씨 상황을 표준화한 Context 데이터 계약.

    필드:
    - status: 맑음/흐림/비/눈 등 요약 상태
    - temperature_c: 섭씨 온도
    - precipitation_type: none/rain/snow 등 강수 유형
    - precipitation_probability: 강수 확률
    - walk_message_seed: 에이전트가 산책 안내 문구를 만들 때 참고할 구조화 데이터
    - raw: optional. 디버깅/추적용 원본 데이터

    TODO:
    - status와 precipitation_type의 허용값을 확정한다.
    - 날씨 provider별 raw field mapping 표준을 정한다.
    """
    status: str | None
    temperature_c: float | None
    precipitation_type: str | None
    precipitation_probability: float | None
    walk_message_seed: dict[str, Any]
    raw: dict[str, Any] | None

    pass

def create_weather_context(raw_weather: dict[str, Any]) -> dict[str, Any]:
    """
    외부 API에서 가져온 raw 날씨 데이터를 서비스 내부 규격으로 포장한다.

    담당:
    - 날씨 상태, 온도, 강수 여부 파싱
    - 산책 추천 메시지 seed 생성

    금지:
    - 실제 날씨 API(기상청 등) 호출 금지 (데이터는 인자로 받아야 함)

    TODO:
    - raw_weather provider별 mapping table을 정한다.
    - UIEvent weather_card payload와 필드명을 맞춘다.
    """
    pass
