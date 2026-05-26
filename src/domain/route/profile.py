from typing import Any

class Profile:
    """
    사용자의 테마/의도를 가중치 룰로 정의하는 핵심 계약.

    담당:
    - name (프로필 이름, 예: quiet_profile)
    - description (프로필 목적)
    - weights (Feature별 적용할 가중치 딕셔너리)
    - filters (절대 지나가면 안 되는 필터 조건)
    - required_features (이 프로필을 위해 반드시 필요한 Feature 리스트)

    금지:
    - 그래프 연산, 스코어 계산 로직 포함 금지

    TODO:
    - filters의 표준 key 목록을 route_engine/profiles 문서와 맞춘다.
    - LLM이 생성한 dynamic profile도 같은 구조를 따르게 한다.
    """
    name: str
    description: str
    weights: dict[str, float]
    filters: dict[str, Any]
    required_features: list[str]
    metadata: dict[str, Any]

    pass
