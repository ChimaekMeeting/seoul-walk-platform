from typing import Any

def graph_path_to_coordinates(graph: Any, path: list[Any]) -> list[list[float]]:
    """
    graph와 path node 리스트를 좌표 리스트([[lat, lon], ...])로 변환합니다.

    금지:
    - 자연어 설명 생성, UI event 생성, route algorithm 호출 금지

    TODO:
    - node 좌표 vs. edge geometry 사용 정책을 확정합니다.
    - GeoJSON 변환 책임을 result 계층과 분리합니다.
    """
    pass

