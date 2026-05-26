from typing import Any

def build_text_event(text: str) -> dict[str, Any]:
    """
    텍스트 채팅 UIEvent 생성.

    반환 계약:
    - type: "text"
    - payload: {"message": text}

    금지:
    - Streamlit/React Native 렌더링 코드 작성 금지
    - LLM 자연어 생성 호출 금지
    """
    pass

def build_weather_card_event(payload: dict[str, Any]) -> dict[str, Any]:
    """
    날씨 카드 UIEvent 생성.

    반환 계약:
    - type: "weather_card"
    - payload: 날씨/미세먼지 카드 렌더링에 필요한 구조화 데이터

    예상 payload:
    - weather_status
    - weather_message
    - air_status
    - air_message
    """
    pass

def build_map_event(route_result: Any) -> dict[str, Any]:
    """
    경로 결과를 바탕으로 지도 렌더링 UIEvent 생성.

    반환 계약:
    - type: "map"
    - payload: geojson, coordinates, center, overlays 등 지도 렌더링 데이터

    금지:
    - folium/React Native 지도 컴포넌트 직접 import 금지
    """
    pass

def build_route_card_event(route_result: Any) -> dict[str, Any]:
    """
    경로 요약 카드 UIEvent 생성.

    반환 계약:
    - type: "route_card"
    - payload: 거리, 예상 시간, 주요 feature, 추천 이유 seed 등
    """
    pass

def build_poi_overlay_event(pois: list[dict[str, Any]]) -> dict[str, Any]:
    """
    지도 위에 POI 마커를 덧씌우는 UIEvent 생성.

    반환 계약:
    - type: "poi_overlay"
    - payload: {"pois": pois}

    주의:
    - POI 조회 자체는 context 또는 infrastructure 계층 책임이다.
    - 이 함수는 조회된 POI를 UIEvent 형태로 포장하는 책임만 가진다.
    """
    pass
