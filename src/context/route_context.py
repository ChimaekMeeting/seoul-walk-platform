from typing import Any

class RouteContext:
    """
    경로 탐색(Route Recommendation) 시 활용될 모든 상황 정보를 하나로 합친 종합 Context 계약.

    필드:
    - weather: WeatherContext dict
    - air_quality: AirQualityContext dict
    - live_poi: LivePoiContext dict
    - user_location: UserLocationContext dict
    - request_tags: 에이전트/application이 붙인 현재 요청 태그
    - metadata: trace_id, source, created_at 등 확장 정보

    TODO:
    - RouteRequest.context에 들어갈 최소 필드와 optional 필드를 확정한다.
    - application/route_recommendation/route_context_builder와 책임 경계를 맞춘다.
    """
    weather: dict[str, Any] | None
    air_quality: dict[str, Any] | None
    live_poi: dict[str, Any] | None
    user_location: dict[str, Any] | None
    request_tags: list[str]
    metadata: dict[str, Any]

    pass

def build_combined_route_context(
    weather: dict[str, Any] | None,
    air_quality: dict[str, Any] | None,
    live_poi: dict[str, Any] | None,
    user_location: dict[str, Any] | None
) -> dict[str, Any]:
    """
    개별적으로 표준화된 여러 상황(Context) 정보들을
    하나의 종합적인 거대 RouteContext 딕셔너리로 합쳐서 반환한다.

    담당:
    - 각 부분 컨텍스트 병합 (Merge)

    금지:
    - 이 함수 내에서 route_engine을 직접 호출 금지

    TODO:
    - None context를 빈 dict로 다룰지, 그대로 None으로 유지할지 결정한다.
    - route_engine에 넘길 context와 UIEvent에 넘길 context를 분리할지 결정한다.
    """
    pass
