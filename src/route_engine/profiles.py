from typing import Union
from pydantic import BaseModel

from src.interfaces.schema.walk_schema import WalkMode
from src.schema.route_schema import Weights


class ProfileConfig(BaseModel):
    weights:      Weights
    blocked_tags: list[str] = []


_DEFAULT = ProfileConfig(
    weights=Weights(safety=0.5, nature=0.5, slope=0.5),
    blocked_tags=["underground"],
)


# 모드별 가중치 프로필 매핑 (현재 3개 모드 모두 기본 프로필 사용)
PROFILES: dict[WalkMode, ProfileConfig] = {
    WalkMode.CIRCULAR_RANDOM: _DEFAULT,
    WalkMode.ONEWAY_SHORTEST: _DEFAULT,
    WalkMode.ONEWAY_RANDOM:   _DEFAULT,
}


# ── 진입점 ────────────────────────────────────────────────

def get_profile(profile_name: Union[str, WalkMode]) -> ProfileConfig:
    return PROFILES.get(profile_name, _DEFAULT)
