from typing import Any

def filter_graph_by_request(graph: Any, request: dict[str, Any]) -> Any:
    """
    요청 조건에 맞게 graph의 범위나 후보 edge를 제한합니다.

    담당:
    - 현재 위치 반경 필터링
    - 목적지/거리 기반 탐색 범위 제한

    금지:
    - feature 점수 계산, custom_score 계산, route algorithm 호출 금지

    TODO: graph 직접 수정 vs. copy 반환 정책을 확정합니다.
    """
    pass

