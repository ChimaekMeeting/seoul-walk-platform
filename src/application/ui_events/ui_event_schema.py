from typing import Any

class TextPayload:
    """
    type="text" UIEvent의 payload 계약.

    필드:
    - message: 사용자에게 보여줄 텍스트
    - tone: optional. friendly, warning, info 등 표현 톤

    TODO:
    - tone 허용값을 프론트 팀과 확정한다.
    """
    message: str
    tone: str | None
    pass

class WeatherCardPayload:
    """
    type="weather_card" UIEvent의 payload 계약.

    필드:
    - weather_status: 맑음/흐림/비 등 요약 상태
    - weather_msg: 산책 추천에 사용할 날씨 문구
    - air_status: 미세먼지 상태
    - air_msg: 미세먼지 안내 문구
    - raw: optional. 디버깅 또는 상세 렌더링용 원본 context

    금지:
    - 이 schema에서 외부 날씨 API 호출 금지
    """
    weather_status: str
    weather_msg: str
    air_status: str | None
    air_msg: str | None
    raw: dict[str, Any] | None
    pass

class MapPayload:
    """
    type="map" UIEvent의 payload 계약.

    필드:
    - geojson: 지도 렌더러가 표시할 경로 GeoJSON
    - coordinates: [[lat, lon], ...] 형태의 좌표 리스트
    - center: 지도 초기 중심 좌표
    - overlays: optional. POI, 구간 highlight 등 추가 레이어

    금지:
    - Folium 또는 React Native 지도 컴포넌트 의존 금지
    """
    geojson: dict[str, Any] | None
    coordinates: list[list[float]]
    center: dict[str, float] | None
    overlays: list[dict[str, Any]]
    pass

class RouteCardPayload:
    """
    type="route_card" UIEvent의 payload 계약.

    필드:
    - total_distance_km: 총 거리
    - duration_min: 예상 소요 시간
    - title: 카드 제목
    - feature_summary: 안전/자연/경사 등 주요 특징 요약
    - explanation_seed: 에이전트가 자연어 설명을 만들 때 사용할 구조화 데이터
    """
    total_distance_km: float
    duration_min: float | None
    title: str | None
    feature_summary: dict[str, Any]
    explanation_seed: dict[str, Any]
    pass

class PoiOverlayPayload:
    """
    type="poi_overlay" UIEvent의 payload 계약.

    필드:
    - pois: 지도에 표시할 주변 편의시설 목록

    예상 poi item:
    {
        "name": str,
        "category": str,
        "lat": float,
        "lon": float,
        "source": "kakao" | "static" | "manual"
    }
    """
    pois: list[dict[str, Any]]
    pass
