# Route Engine - Profiles Layer
# 담당: 승리
# 역할: profile_name을 받아 weights와 blocked_tags 반환

from dataclasses import dataclass, field


@dataclass
class ProfileConfig:
    weights: dict[str, float]
    blocked_tags: list[str] = field(default_factory=list)


# ── 프로필 정의 ──────────────────────────────────────────
# final_cost = length_m + sum(feature_value * weight)
# final_cost가 낮을수록 좋은 길
# 좋은 요소 → 음수 weight (cost 낮춤)
# 피할 요소 → 양수 weight (cost 높임)

PROFILES: dict[str, ProfileConfig] = {

    # 기본값 — 특별한 조건 없음
    "default": ProfileConfig(
        weights={
            "safety":    -20.0,
            "slope":      30.0,
            "quietness": -10.0,
            "scenery":   -10.0,
            "shade":     -10.0,
        },
        blocked_tags=["construction"],
    ),

    # 조용한 길 — 한적하고 사람 적은 곳
    "quiet": ProfileConfig(
        weights={
            "safety":    -20.0,
            "slope":      20.0,
            "quietness": -80.0,  # 조용함 최우선
            "scenery":   -10.0,
            "shade":     -10.0,
        },
        blocked_tags=["construction"],
    ),

    # 평지 — 경사 없는 길
    "flat": ProfileConfig(
        weights={
            "safety":    -20.0,
            "slope":     100.0,  # 경사 최대 페널티
            "quietness": -10.0,
            "scenery":   -10.0,
            "shade":     -10.0,
        },
        blocked_tags=["construction"],
    ),

    # 안전한 길 — 밝고 CCTV 많은 곳
    "safe": ProfileConfig(
        weights={
            "safety":    -80.0,  # 안전 최우선
            "slope":      30.0,
            "quietness":  10.0,  # 사람 있는 길 선호 (조용함 페널티)
            "scenery":   -10.0,
            "shade":     -10.0,
        },
        blocked_tags=["construction", "alley"],
    ),

    # 경관 좋은 길 — 랜드마크, 풍경
    "scenic": ProfileConfig(
        weights={
            "safety":    -20.0,
            "slope":      20.0,
            "quietness": -10.0,
            "scenery":   -80.0,  # 경관 최우선
            "shade":     -10.0,
        },
        blocked_tags=["construction"],
    ),

    # 어린이 동반 — 안전 + 평지 + 어린이보호구역 우선
    "child": ProfileConfig(
        weights={
            "safety":    -80.0,  # 안전 최우선
            "slope":      80.0,  # 경사 강하게 회피
            "quietness": -10.0,
            "scenery":   -10.0,
            "shade":     -20.0,
        },
        blocked_tags=["highway", "construction", "alley"],
    ),
}


# ── 진입점 ────────────────────────────────────────────────

def get_profile(profile_name: str) -> ProfileConfig:
    """
    profile_name을 받아 ProfileConfig(weights, blocked_tags)를 반환합니다.
    알 수 없는 profile_name이 들어오면 default를 반환합니다.
    """
    return PROFILES.get(profile_name, PROFILES["default"])
