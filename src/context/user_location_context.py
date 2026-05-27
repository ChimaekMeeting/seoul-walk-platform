from typing import Any

class UserLocationContext:
    """
    유저의 위치 정보를 담는 Context 데이터 계약.

    필드:
    - current: 현재 사용자 좌표
    - origin: 실제 산책 출발지 좌표
    - destination: 편도 산책 목적지 좌표
    - address: 현재 위치 또는 출발지 주소 문자열
    - address_candidates: geocoding 결과 후보 목록
    - raw: optional. 디버깅/추적용 원본 데이터

    좌표 dict 표준:
    {
        "lat": float,
        "lon": float
    }

    TODO:
    - 출발지와 현재 위치가 다를 때 우선순위 정책을 정한다.
    """
    current: dict[str, float] | None
    origin: dict[str, float] | None
    destination: dict[str, float] | None
    address: str | None
    address_candidates: list[dict[str, Any]]
    raw: dict[str, Any] | None

    pass

def create_user_location_context(location_payload: dict[str, Any]) -> dict[str, Any]:
    """
    프론트엔드 등에서 넘어온 원시 위치 데이터를 서비스 표준 위치 객체로 포장한다.

    담당:
    - 현재 위치, 출발지, 목적지 좌표 정리
    - 행정동/법정동 주소 후보 문자열 표준화

    금지:
    - 실제 Geocoding API 통신 구현 금지

    TODO:
    - lat/lon 필드 검증을 어디서 할지 결정한다.
    - 주소 후보를 UIEvent로 노출할지 application 내부에서만 쓸지 결정한다.
    """
    pass
