from typing import Any

class LivePoiContext:
    """
    주변 실시간 편의시설(POI) 목록을 담는 Context 데이터 계약.

    필드:
    - pois: 표준화된 POI item 목록
    - categories: 요청 또는 응답에 포함된 POI 카테고리 목록
    - source: kakao/static/manual 등 데이터 출처
    - search_radius_m: POI 검색 반경
    - raw: optional. 디버깅/추적용 원본 데이터

    표준 POI item 예:
    {
        "name": str,
        "category": str,
        "lat": float,
        "lon": float,
        "distance_m": float | None,
        "source": str
    }

    TODO:
    - category 표준값을 프론트/route_engine 문서와 맞춘다.
    - Layer 1.5 POI를 경유 후보로 쓸지, 지도 overlay로만 쓸지 정책을 정한다.
    """
    pois: list[dict[str, Any]]
    categories: list[str]
    source: str | None
    search_radius_m: float | None
    raw: list[dict[str, Any]] | None

    pass

def create_live_poi_context(raw_pois: list[dict[str, Any]]) -> dict[str, Any]:
    """
    외부 API(카카오맵 등)에서 가져온 주변 장소 데이터를
    서비스가 다루기 쉬운 표준 POI 목록(카테고리별)으로 변환한다.

    예상 카테고리 (분류 기준):
    - cafe, convenience_store, restroom, subway, park, hospital, police 등

    금지:
    - 실제 Kakao 지도 API 호출 등 외부 통신 구현 금지

    TODO:
    - Kakao category code를 내부 category로 변환하는 mapping을 정한다.
    - POI deduplication 정책을 정한다.
    """
    pass
