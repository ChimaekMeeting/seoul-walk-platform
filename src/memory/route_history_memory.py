from typing import Any

def load_recent_route_history(user_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """
    최근 경로 추천/산책 이력을 불러올 예정인 함수.

    금지:
    - 현재 단계에서 실제 DB query 구현 금지
    """
    pass

def save_route_history(user_id: str, route_result: dict[str, Any], feedback: dict[str, Any] | None = None) -> None:
    """
    사용자에게 추천했던 산책 경로 이력을 저장한다.

    담당:
    - 중복 추천을 피하거나, 과거 좋았던 경로를 다시 추천하기 위함.

    이후 흐름:
    - infrastructure/repositories 계층에 위임

    금지:
    - 실제 DB 구현 로직 추가 금지
    """
    pass

def get_recent_routes(user_id: str, limit: int = 5) -> list[Any]:
    """
    사용자가 최근에 추천받았거나 완주한 경로 목록을 반환한다.

    호환용 skeleton:
    - 추후 `load_recent_route_history`로 통합할지 결정한다.
    """
    pass
