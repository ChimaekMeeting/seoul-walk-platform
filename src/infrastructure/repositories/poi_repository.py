from typing import Any

def save_static_pois(pois: list[dict[str, Any]]) -> None:
    """
    정적 Layer 1로 편입할 POI를 저장할 예정인 함수.
    실시간 Kakao POI 전체를 무조건 저장하지 않는다.

    저장 대상 예:
    - 공공 화장실
    - 경찰서/지구대
    - 공원/하천 접근점
    - 안심시설

    금지:
    - 현재 단계에서 실제 DB query 구현 금지
    - Kakao raw response를 표준화 없이 그대로 저장하는 구조 금지
    """
    pass

def find_static_pois_near(lat: float, lon: float, radius_m: int) -> list[dict[str, Any]]:
    """
    DB에 저장된 정적 POI를 조회할 예정인 함수.

    반환 예정:
    - context/live_poi_context.py 또는 route_engine features에서 쓰기 쉬운 dict 목록

    금지:
    - 현재 단계에서 실제 PostGIS query 구현 금지
    """
    pass
