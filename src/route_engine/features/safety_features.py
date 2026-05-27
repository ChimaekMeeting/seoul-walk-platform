from typing import Any

def bind_safety_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    """
    Graph edge에 안전 관련 feature를 표준 이름으로 바인딩한다.

    담당:
    - CCTV 밀도
    - 경찰서/지구대 접근성
    - 안심지킴이집 접근성
    - 가로등/안심귀갓길 등

    입력:
    - graph: NetworkX Graph 형태의 도로망
    - context: 현재 요청 context. 없을 수도 있다.

    출력:
    - 안전 feature가 edge attribute에 추가된 graph

    금지:
    - custom_score 계산 금지
    - route algorithm 호출 금지
    - Streamlit/FastAPI 직접 import 금지
    - 기존 route_service import 금지

    TODO:
    - 팀원이 기존 safety 관련 로직을 분석한 뒤 이 함수 내부를 채운다.
    """
    pass
