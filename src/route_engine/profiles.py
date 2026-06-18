from typing import Union
from pydantic import BaseModel

from src.interfaces.schema.walk_schema import CircularMode, OnewayMode
from src.schema.route_schema import Weights


class ProfileConfig(BaseModel):
    weights:      Weights
    blocked_tags: list[str] = []


# ── 프로필 정의 ────────────────────────────────────────────
# Weights 값이 클수록 해당 score를 경로 선택에서 강하게 반영합니다.
# slope는 회피 가중치 — 클수록 경사가 있는 엣지를 피합니다.

PROFILES: dict[str, ProfileConfig] = {

    # 기본값 — 안전·자연 균형
    "default": ProfileConfig(
        weights=Weights(safety=0.5, nature=0.5, slope=0.5),
        blocked_tags=["underground"],
    ),

    # 조용한 길 — 자연환경 최우선
    "quiet": ProfileConfig(
        weights=Weights(safety=0.5, nature=0.8, slope=0.3),
        blocked_tags=["underground"],
    ),

    # 평지 — 경사 강하게 회피
    "flat": ProfileConfig(
        weights=Weights(safety=0.5, nature=0.3, slope=1.0),
        blocked_tags=["underground"],
    ),

    # 안전한 길 — 밝고 CCTV 많은 곳
    "safe": ProfileConfig(
        weights=Weights(safety=1.0, nature=0.3, slope=0.5),
        blocked_tags=["underground", "alley"],
    ),

    # 경관 좋은 길 — 랜드마크·풍경 최우선
    "scenic": ProfileConfig(
        weights=Weights(safety=0.5, nature=0.5, slope=0.3, landmark=1.0),
        blocked_tags=["underground"],
    ),

    # 어린이 동반 — 안전 + 평지 + 어린이보호구역
    "child": ProfileConfig(
        weights=Weights(safety=1.0, nature=0.3, slope=1.0, child=1.0),
        blocked_tags=["underground", "highway"],
    ),

    # 러닝 — 러닝 코스 우선
    "running": ProfileConfig(
        weights=Weights(safety=0.5, nature=0.5, slope=0.7, running=1.0),
        blocked_tags=["underground"],
    ),
}


# ── 진입점 ────────────────────────────────────────────────

def get_profile(profile_name: Union[str, OnewayMode, CircularMode]) -> ProfileConfig:
    return PROFILES.get(profile_name, PROFILES["default"])
