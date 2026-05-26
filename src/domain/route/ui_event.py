from typing import Any, Literal

class UIEvent:
    """
    에이전트가 프론트엔드에 '어떤 화면을 그려라'라고 지시하는 핵심 계약.

    담당:
    - type (text, weather_card, map, route_card, poi_overlay 중 하나)
    - payload (해당 위젯을 그리기 위한 데이터 딕셔너리)

    금지:
    - 실제 UI 프레임워크(Streamlit, React Native) 코드 임포트 금지

    TODO:
    - 프론트 팀과 협의하여 event type 목록을 확정한다.
    - payload별 세부 schema를 schemas 또는 frontend contract 문서로 분리한다.
    """
    # 허용 event type:
    # - text: 채팅/추천 문구
    # - weather_card: 날씨/미세먼지 카드
    # - map: 경로 지도
    # - route_card: 추천 경로 요약 카드
    # - poi_overlay: 주변 편의시설 오버레이
    type: Literal["text", "weather_card", "map", "route_card", "poi_overlay"]
    payload: dict[str, Any]
    source: Literal["application", "agent", "route_engine"] | None
    correlation_id: str | None

    pass
