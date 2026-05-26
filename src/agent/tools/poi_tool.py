from typing import Any, Optional

def get_live_poi_context(lat: float, lon: float, categories: Optional[list[str]] = None) -> dict[str, Any]:
    """
    주변 POI context를 가져오는 agent tool 예정 함수.

    예정 흐름:
    1. infrastructure/external/kakao_client로 raw POI 조회
    2. context/live_poi_context로 표준화
    3. 표준 POI context 반환

    현재 단계에서는 실제 Kakao API 호출 구현 금지.
    """
    pass
