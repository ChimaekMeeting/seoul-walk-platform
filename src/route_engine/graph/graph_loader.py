from typing import Any

def load_route_graph(request: dict[str, Any]) -> Any:
    """
    현재 추천 요청에 필요한 주변 도로망 graph를 준비한다.

    예정 역할:
    - 사용자 현재 위치와 목표 거리 기준으로 필요한 graph 범위를 결정한다.
    - PostGIS/DB에서 도로망을 읽거나, application 계층에서 주입받은 graph를 표준화한다.
    - edge에는 최소한 `length`, `geometry`, 정적 Layer 1 feature들이 포함될 수 있도록 한다.

    입력:
    - request: RouteRequest 또는 그에 준하는 dict

    출력:
    - route_engine 표준 NetworkX Graph 형태의 도로망

    금지:
    - custom_score 계산 금지
    - profile 선택 금지
    - route algorithm 호출 금지
    - 기존 `src/service/route` import 금지

    TODO:
    - DB에서 직접 로드할지, application 계층에서 graph를 주입할지 정책을 확정한다.
    - 표준 node/edge attribute 목록을 문서화한다.
    """
    pass

