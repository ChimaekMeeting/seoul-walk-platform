from typing import Any

def recommend_route(request: dict[str, Any]) -> dict[str, Any]:
    """
    명시적 경로 추천 API 계약.

    예상 요청:
    - user_id
    - origin
    - destination
    - mode
    - distance_km
    - profile_name
    - preferences
    - context

    예정 흐름:
    - application/route_recommendation.recommend_route_usecase 호출
    - RouteResult 또는 UIEvent 목록 반환

    금지:
    - route_engine 직접 구현 금지
    - NetworkX 조작 금지
    - 현재 단계에서 실제 application 호출 구현 금지
    """
    pass
