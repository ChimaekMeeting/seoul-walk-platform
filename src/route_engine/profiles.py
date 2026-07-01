from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel

from src.schema.route_schema import Weights


class ScoringProfile(str, Enum):
    """
    경로 생성 방식(WalkMode)과는 별개로, 어떤 score 조합을 선호할지 결정하는 프로필입니다.
    WalkMode(circular_random/oneway_shortest/oneway_random)와 자유롭게 조합됩니다.
    """
    DEFAULT  = "default"
    NATURE   = "nature"
    SAFE     = "safe"
    FLAT     = "flat"
    RUNNING  = "running"
    LANDMARK = "landmark"
    CHILD    = "child"


class ProfileConfig(BaseModel):
    weights:      Weights
    blocked_tags: list[str] = []
    # scoring_engine.calculate_custom_score가 받는 "general" | "running" 계산 분기.
    # running 프로필만 running_score/역방향 slope 공식을 쓰는 "running" 분기를 사용합니다.
    scoring_mode: str = "general"


PROFILES: dict[ScoringProfile, ProfileConfig] = {
    ScoringProfile.DEFAULT: ProfileConfig(
        weights=Weights(safety=0.5, nature=0.5, slope=0.5),
        blocked_tags=["underground"],
    ),
    ScoringProfile.NATURE: ProfileConfig(
        weights=Weights(safety=0.5, nature=0.8, slope=0.5),
        blocked_tags=["underground"],
    ),
    ScoringProfile.SAFE: ProfileConfig(
        weights=Weights(safety=0.8, nature=0.5, slope=0.5),
        blocked_tags=["underground"],
    ),
    ScoringProfile.FLAT: ProfileConfig(
        weights=Weights(safety=0.5, nature=0.5, slope=0.8),
        blocked_tags=["underground"],
    ),
    ScoringProfile.RUNNING: ProfileConfig(
        weights=Weights(safety=0.5, nature=0.5, slope=0.5, running=0.8),
        blocked_tags=["underground"],
        scoring_mode="running",
    ),
    ScoringProfile.LANDMARK: ProfileConfig(
        weights=Weights(safety=0.5, nature=0.5, slope=0.5, landmark=0.8),
        blocked_tags=["underground"],
    ),
    ScoringProfile.CHILD: ProfileConfig(
        weights=Weights(safety=0.5, nature=0.5, slope=0.5, child=0.8),
        blocked_tags=["underground"],
    ),
}

_DEFAULT = PROFILES[ScoringProfile.DEFAULT]


# ── 진입점 ────────────────────────────────────────────────

def get_profile(profile: Union[str, ScoringProfile, None]) -> ProfileConfig:
    """profile/theme 이름으로 ProfileConfig를 조회합니다. 알 수 없거나 None이면 default."""
    if profile is None:
        return _DEFAULT
    try:
        key = ScoringProfile(profile)
    except ValueError:
        return _DEFAULT
    return PROFILES.get(key, _DEFAULT)


def merge_weights(base: Weights, custom_weights: Optional[Weights]) -> Weights:
    """
    profile.weights(base)를 기본값으로 두고, custom_weights에서 명시적으로
    설정된 필드만 override하여 합칩니다. custom_weights가 None이면 base 그대로 반환합니다.
    """
    if custom_weights is None:
        return base
    merged = base.model_dump()
    merged.update(custom_weights.model_dump(exclude_unset=True))
    return Weights(**merged)
