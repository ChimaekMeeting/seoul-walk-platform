from typing import Any

def build_route_result(raw_path: Any, graph: Any) -> dict[str, Any]:
    """
    탐색 엔진이 뱉어낸 raw 경로 데이터를 앱에서 그리기 쉬운
    표준 포맷(RouteResult)으로 포장한다.

    예상 출력 구조:
    - coordinates
    - geojson
    - total_distance_km
    - duration_min
    - used_features
    - explanation_seed
    - nearby_pois

    주의:
    - 최종 자연어 문장 생성은 이 함수의 책임이 아님. 오직 구조화된 데이터 조립.
    """
    pass
