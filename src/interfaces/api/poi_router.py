from typing import Any

def get_nearby_pois(request: dict[str, Any]) -> dict[str, Any]:
    """
    현재 위치 주변 POI context 조회 API 계약.

    예상 요청:
    - lat
    - lon
    - categories
    - radius_m

    반환 예정:
    - 표준화된 POI context 또는 poi_overlay UIEvent payload

    금지:
    - 실제 Kakao API 호출 구현 금지
    - 현재 단계에서 실제 application/agent 호출 구현 금지
    """
    pass
