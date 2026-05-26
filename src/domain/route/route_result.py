from typing import Any

class RouteResult:
    """
    Route Engine이 탐색을 완료하고 반환하는 핵심 계약.

    담당:
    - coordinates (경로 위경도 배열)
    - geojson (맵 렌더링용 표준 포맷)
    - total_distance_km (총 거리)
    - duration_min (예상 소요 시간)
    - used_features (경로에 포함된 주요 특징들)
    - explanation_seed (LLM이 설명 문구를 생성할 때 쓸 재료 데이터)
    - nearby_pois (경로 주변 편의시설)

    금지:
    - 자연어 문장 직접 생성 로직 포함 금지

    TODO:
    - coordinates와 geojson 중 어느 쪽을 route_engine의 1차 표준 출력으로 삼을지 결정한다.
    - nearby_pois를 route_result에 포함할지, UIEvent payload에서 합칠지 결정한다.
    """
    coordinates: list[list[float]]
    geojson: dict[str, Any]
    total_distance_km: float
    duration_min: float | None
    used_features: list[str]
    feature_summary: dict[str, Any]
    explanation_seed: dict[str, Any]
    nearby_pois: list[dict[str, Any]]
    raw_path: list[Any]

    pass
