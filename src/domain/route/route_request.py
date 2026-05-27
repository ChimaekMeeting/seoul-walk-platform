from typing import Any, Literal

class RouteRequest:
    """
    경로 탐색을 위해 Route Engine에 전달되는 핵심 계약.

    담당:
    - 사용자 위치 (출발지)
    - 목표 거리 (km/m)
    - 순환/편도 여부
    - 목적지 (편도일 경우)
    - 자연어 의도 (LLM이 파악한 원래 질문)
    - profile name (적용할 가중치 테마)
    - preferences (추가적인 사용자 선호 필터)

    금지:
    - FastAPI Request 객체 직접 상속/사용 금지
    - 외부 라이브러리 의존 금지

    TODO:
    - 추후 dataclass 또는 Pydantic 모델로 전환할지 결정한다.
    - origin/destination을 별도 Location 도메인 객체로 분리할지 결정한다.
    """
    user_id: str | None
    origin: dict[str, float]
    mode: Literal["circular", "oneway"]
    distance_km: float | None
    destination: dict[str, float] | None
    intent_text: str | None
    profile_name: str | None
    preferences: dict[str, Any]
    context: dict[str, Any]

    pass
