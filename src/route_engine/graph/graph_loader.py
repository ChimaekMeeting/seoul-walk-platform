from typing import Any

def load_route_graph(request: dict[str, Any]) -> Any:
    """
    추천 요청에 필요한 도로망 graph를 준비합니다.

    담당:
    - 사용자 위치와 목표 거리 기준으로 graph 범위를 결정합니다.
    - PostGIS/DB에서 도로망을 읽거나 주입받은 graph를 표준화합니다.

    금지:
    - custom_score 계산, profile 선택, route algorithm 호출 금지
    - 기존 src/service/route import 금지

    TODO:
    - DB 직접 로드 vs. graph 주입 정책을 확정합니다.
    - 표준 node/edge attribute 목록을 문서화합니다.
    """
    pass

