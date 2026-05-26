from typing import Any

def search_nearby_places(lat: float, lon: float, category: str | None = None, radius_m: int = 1000) -> list[dict[str, Any]]:
    """
    Kakao Map API에서 현재 위치 주변 POI raw data를 조회할 예정인 함수.

    담당:
    - 카페, 편의점, 화장실, 지하철역, 경찰서 등 주변 장소 조회
    - raw Kakao response 반환

    이후 흐름:
    - 이 함수의 raw response는 context/live_poi_context.py에서 내부 표준 POI로 변환된다.

    금지:
    - 현재 단계에서 requests/httpx 등 실제 HTTP 호출 구현 금지

    주의:
    - 이 함수는 raw Kakao response를 반환하는 boundary adapter이다.
    - `place_name`, `category_name`, `x`, `y`, `distance` 같은 Kakao 필드명을
      서비스 내부 표준 필드로 바꾸는 작업은 context/live_poi_context.py의 책임이다.
    - 실시간 POI 전체를 DB에 저장하지 않는다. 저장 여부는 repository/data collector 정책에서 결정한다.

    TODO:
    - Kakao category code와 내부 category 이름의 mapping 위치를 정한다.
    - keyword search와 category search를 함수로 분리할지 결정한다.
    """
    pass

def reverse_geocode(lat: float, lon: float) -> dict[str, Any]:
    """
    Kakao 좌표->주소 변환 raw data 조회 예정 함수.

    이후 흐름:
    - raw response는 context/user_location_context.py에서 표준 위치 context로 변환된다.

    금지:
    - 현재 단계에서 실제 HTTP 호출 구현 금지
    - application/domain/route_engine으로 Kakao raw field를 직접 노출 금지
    """
    pass
