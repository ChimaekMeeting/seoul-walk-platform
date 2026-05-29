from typing import Any

def build_route_result(raw_path: Any, graph: Any) -> dict[str, Any]:
    """
    탐색 엔진의 raw 경로 데이터를 표준 포맷(RouteResult)으로 변환합니다.

    출력 필드: coordinates, geojson, total_distance_km, duration_min,
    used_features, explanation_seed, nearby_pois

    주의: 자연어 문장 생성은 이 함수의 책임이 아닙니다.
    """
    pass
