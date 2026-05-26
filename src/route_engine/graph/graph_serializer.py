from typing import Any

def graph_path_to_coordinates(graph: Any, path: list[Any]) -> list[list[float]]:
    """
    graph와 path node 리스트를 앱에서 그리기 쉬운 좌표 리스트로 변환한다.

    예정 출력:
    - [[lat, lon], [lat, lon], ...]

    금지:
    - 자연어 설명 생성 금지
    - UI event 생성 금지
    - route algorithm 호출 금지

    TODO:
    - node 좌표를 사용할지 edge geometry를 사용할지 정책을 정한다.
    - GeoJSON 변환 책임을 result 계층과 어떻게 나눌지 정한다.
    """
    pass

