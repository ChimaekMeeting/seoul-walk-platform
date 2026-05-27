from typing import Any

def filter_graph_by_request(graph: Any, request: dict[str, Any]) -> Any:
    """
    추천 요청 조건에 맞게 graph의 범위나 후보 edge를 제한한다.

    예정 역할:
    - 현재 위치 반경 필터링
    - 목적지/거리 기반 탐색 범위 제한
    - 명백히 사용할 수 없는 edge 제거 또는 표시

    금지:
    - feature 점수 계산 금지
    - custom_score 계산 금지
    - route algorithm 호출 금지

    TODO:
    - 필터링이 graph를 직접 변경할지 copy를 반환할지 정책을 정한다.
    """
    pass

