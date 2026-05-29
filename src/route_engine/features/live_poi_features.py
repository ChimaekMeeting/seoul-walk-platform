from typing import Any

def bind_live_poi_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    """
    graph edge에 실시간 POI(편의시설, 화장실 등) 접근성 feature를 바인딩합니다.

    금지:
    - 외부 API 직접 호출 금지 (context로 전달받아야 합니다)
    - custom_score 계산, route algorithm 호출 금지

    TODO: 실시간 POI 로직을 구현합니다.
    """
    pass
