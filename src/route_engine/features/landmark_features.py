from typing import Any

def bind_landmark_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    """
    graph edge에 랜드마크 접근성(landmark_score) feature를 바인딩합니다.

    금지:
    - custom_score 계산, route algorithm 호출, Streamlit/FastAPI import 금지

    TODO: 기존 랜드마크 로직을 분석하여 함수 내부를 구현합니다.
    """
    pass
