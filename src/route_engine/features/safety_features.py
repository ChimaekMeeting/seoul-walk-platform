from typing import Any

def bind_safety_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    """
    graph edge에 안전 관련 feature(CCTV 밀도, 경찰서/지구대 접근성 등)를 바인딩합니다.

    금지:
    - custom_score 계산, route algorithm 호출, Streamlit/FastAPI import 금지

    TODO: 기존 safety 관련 로직을 분석하여 함수 내부를 구현합니다.
    """
    pass
