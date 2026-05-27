from typing import Literal

class FeatureSpec:
    """
    각 Feature 도구가 어떤 데이터를 다루는지 명세하는 핵심 계약.

    담당:
    - feature name (예: safety_score)
    - description (설명)
    - value range (값의 범위, 예: 0.0 ~ 1.0)
    - higher_is_better (높을수록 좋은지 여부 boolean)
    - source_layer (static/live/memory 출처)
    - owner (이 데이터를 담당하는 팀원)

    금지:
    - 실제 데이터 파싱/바인딩 로직 포함 금지

    TODO:
    - value_range 표현을 tuple로 유지할지 별도 ValueRange 객체로 분리할지 결정한다.
    - owner를 팀원 이름으로 둘지 팀/역할 이름으로 둘지 결정한다.
    """
    name: str
    description: str
    value_range: tuple[float, float] | None
    higher_is_better: bool
    source_layer: Literal["static", "live", "memory"]
    owner: str | None
    edge_attribute_name: str
    default_value: float | int | str | None

    pass
