import logging

from src.schema.prewalk_schema import State, FeatureTag
from src.interfaces.schema.walk_schema import WalkMode, Coordinate
from src.agent.tools.route_tools import RouteTool
from src.schema.route_schema import Weights
from src.repository.user.user_preference_repository import UserPreferenceRepository
from src.route_engine.profiles import ScoringProfile, get_profile

logger = logging.getLogger(__name__)

MODE_TOOL_MAP: dict[WalkMode, str] = {
    WalkMode.CIRCULAR_RANDOM: "circular_random_route",
    WalkMode.ONEWAY_SHORTEST: "oneway_shortest_route",
    WalkMode.ONEWAY_RANDOM:   "oneway_random_route",
    WalkMode.GPS_ART:         "gps_art_route",
    WalkMode.WAYPOINT:        "waypoint_route",
}

# feature 라벨·설문이 없을 때의 기본 가중치(baseline).
# route_schema.Weights 기본값을 단일 출처(SSOT)로 사용함.
#   (안전/평지 0.5, 미관·활동·동반 0.0 → 일반 경로 = 해당 특성 무편향)
_BASELINE_WEIGHTS = Weights().model_dump()

# preference_label -> EMA 목표값(target). 이 특징을 얼마나 중요하게 여기는지.
_PREFERENCE_TARGET_MAP: dict[str, float] = {
    "must":    0.95,
    "high":    0.75,
    "neutral": 0.50,
    "low":     0.25,
}

# explicitness_label -> EMA 블렌딩 강도(alpha, 0~1). 클수록 target 쪽으로 세게 끌어당김.
# base[key] = alpha * target + (1 - alpha) * base[key]
# inferred는 alpha=0이라 baseline을 그대로 유지 — 결과상 "언급 안 함"과 동일하다.
_EXPLICITNESS_ALPHA_MAP: dict[str, float] = {
    "explicit_hard": 0.90,
    "explicit_soft": 0.70,
    "optional":      0.40,
    "inferred":      0.00,
}

# FeatureTag -> Weights 필드명. safety는 필드명이 그대로 같고, comfort는 "평지 위주의
# 편안함"으로 해석해 slope(경사 회피)에 반영한다.
_FEATURE_TO_WEIGHTS_KEY: dict[FeatureTag, str] = {
    FeatureTag.SAFETY:  "safety",
    FeatureTag.COMFORT: "slope",
}

class RouteExecutor:
    def __init__(self):
        from src.interfaces.dependencies import get_gps_art_service
        self.route_tool = RouteTool(get_gps_art_service())

    async def run(self, state: State) -> State:
        """
        UserPreference와 feature 라벨을 반영한 가중치로 경로를 생성합니다.
        """
        # 예외1. 모드와 매핑되는 경로 생성 엔진이 없는 경우
        tool_name = MODE_TOOL_MAP.get(state.mode)
        if not tool_name:
            logger.warning(f"모드와 매핑되는 경로 생성 엔진이 없습니다: mode = {state.mode}")
            return state

        context_dump = state.user_context.model_dump(exclude={"mode"}, exclude_none=True)
        legs         = context_dump.pop("legs", None)  # waypoint 모드 전용: leg_modes/leg_target_km로 분리

        args = {}
        for k, v in context_dump.items():
            if k in ("origin", "destination"):
                args[k] = Coordinate(lat=v["lat"], lon=v["lon"])
            elif k == "waypoints":
                args[k] = [Coordinate(lat=wp["lat"], lon=wp["lon"]) for wp in v]
            else:
                args[k] = v

        if legs is not None:
            args["leg_modes"]     = [leg["mode"] for leg in legs]
            args["leg_target_km"] = [leg["target_km"] for leg in legs]

        args["access_token"]   = state.access_token or ""
        profile = state.profile or ScoringProfile.DEFAULT
        state.profile = profile
        args["profile"] = profile
        args["custom_weights"] = self._build_weights(state, profile)

        logger.info(f"mode: {state.mode}")
        logger.info(f"custom_weights: {args['custom_weights']}")

        # 경로 생성
        try:
            state.route_result = await self.route_tool.tool_map[tool_name].ainvoke(args)
        except Exception:
            # 예외2. 경로 생성에 실패한 경우
            logger.exception("경로 생성에 실패했습니다.")
            return state

        return state

    def _build_weights(
        self,
        state: State,
        profile: ScoringProfile = ScoringProfile.DEFAULT,
    ) -> Weights:
        """
        UserPreference base weights에 state.feature_labels의 라벨을 EMA 블렌딩해
        최종 Weights를 반환합니다. UserPreference가 없으면 _BASELINE_WEIGHTS를 사용합니다.
        (안전/평지는 0.5, 미관·활동·동반 특성은 0.0 → 일반 경로는 해당 특성 무편향)
        """
        preference = UserPreferenceRepository.get_by_user_id(state.user_id)
        if preference is None:
            logger.debug("UserPreference가 없어, baseline 가중치를 사용합니다.")

        # 선택 프로필을 기준으로, 저장된 설문값은 전역 baseline과의 차이만 반영합니다.
        # 따라서 사용자 개인화가 convenient/accessible 프로필 자체를 덮어쓰지 않습니다.
        base = get_profile(profile).weights.model_dump()
        for key, default in _BASELINE_WEIGHTS.items():
            stored = (
                getattr(preference, f"weights_{key}", None)
                if preference is not None
                else None
            )
            if stored is not None:
                base[key] = max(0.0, min(1.0, base[key] + stored - default))

        # feature 라벨은 EMA 블렌딩으로 반영. preference_label이 target을,
        # explicitness_label이 alpha(블렌딩 강도)를 정한다.
        for tag, label in state.feature_labels.items():
            key = _FEATURE_TO_WEIGHTS_KEY.get(tag)
            if key is None:
                continue
            target = _PREFERENCE_TARGET_MAP[label.preference_label]
            alpha  = _EXPLICITNESS_ALPHA_MAP[label.explicitness_label]
            base[key] = alpha * target + (1 - alpha) * base[key]

        weights = Weights(**base)
        return weights
