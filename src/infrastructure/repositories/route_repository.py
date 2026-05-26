from typing import Any

def load_walk_graph_near(lat: float, lon: float, radius_m: int) -> Any:
    """
    PostGIS 도로망을 route_engine graph로 로드할 예정인 함수.

    담당:
    - 현재 위치와 반경 기준 도로망 후보를 조회할 예정
    - Layer 1 정적 feature(safety/nature/slope 등)를 함께 로드할 예정
    - route_engine/graph/graph_loader.py가 사용할 수 있는 graph 형태로 전달할 예정

    금지:
    - 현재 단계에서 SQLAlchemy/PostGIS query 구현 금지
    - route algorithm 실행 금지
    - custom_score 계산 금지

    TODO:
    - repository가 NetworkX Graph를 직접 반환할지, raw rows를 반환하고 graph_loader가 조립할지 결정한다.
    """
    pass
