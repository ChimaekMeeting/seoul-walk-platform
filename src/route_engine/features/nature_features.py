from typing import Any

def bind_nature_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    """
    graph edge에 자연 관련 feature(park_accessibility, river_accessibility 등)를 바인딩합니다.

    금지:
    - custom_score 계산, route algorithm 호출, Streamlit/FastAPI import 금지

    TODO: 기존 nature 관련 로직을 분석하여 함수 내부를 구현합니다.
    """
    pass
