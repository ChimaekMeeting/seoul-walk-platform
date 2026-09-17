import logging

from src.schema.prewalk_schema import State, FeatureTag
from src.interfaces.schema.walk_schema import WalkMode, Coordinate
from src.agent.tools.route_tools import RouteTool
from src.schema.route_schema import Weights
from src.repository.user.user_preference_repository import UserPreferenceRepository
from src.route_engine.profiles import ScoringProfile

logger = logging.getLogger(__name__)

MODE_TOOL_MAP: dict[WalkMode, str] = {
    WalkMode.CIRCULAR_RANDOM: "circular_random_route",
    WalkMode.ONEWAY_SHORTEST: "oneway_shortest_route",
    WalkMode.ONEWAY_RANDOM:   "oneway_random_route",
    WalkMode.GPS_ART:         "gps_art_route",
    WalkMode.WAYPOINT:        "waypoint_route",
}

_SURVEY_AXES = ("safety", "comfort")

_PREFERENCE_TARGET_MAP: dict[str, float] = {
    "must":    0.95,
    "high":    0.75,
    "neutral": 0.50,
    "low":     0.25,
}
_EXPLICITNESS_ALPHA_MAP: dict[str, float] = {
    "explicit_hard": 0.90,
    "explicit_soft": 0.70,
    "optional":      0.40,
    "inferred":      0.00,
}

_FEATURE_TO_WEIGHTS_KEY: dict[FeatureTag, str] = {
    FeatureTag.SAFETY:  "safety",
    FeatureTag.COMFORT: "comfort",
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
        args["custom_weights"] = self._build_weights(state)

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

    def _build_weights(self, state: State) -> Weights:
        """
        safety/comfort 두 feature에 대하여 가중치를 누적하여 반환합니다.
        """
        preference = UserPreferenceRepository.get_by_user_id(state.user_id)
        base = {"safety": 0.5, "comfort": 0.5}  # route_schema.Weights의 safety/slope 기본값과 동일

        for key in _SURVEY_AXES:
            stored = getattr(preference, f"weights_{key}", None) if preference is not None else None
            if stored is not None:
                base[key] = max(0.0, min(1.0, stored))

        # 가중치 누적
        for tag, label in state.feature_labels.items():
            key = _FEATURE_TO_WEIGHTS_KEY.get(tag)
            if key is None:
                continue
            target = _PREFERENCE_TARGET_MAP[label.preference_label]     # 선호도 라벨 -> 챗봇 가중치로 사용
            alpha  = _EXPLICITNESS_ALPHA_MAP[label.explicitness_label]  # 명시적 라벨 -> alpha값으로 사용
            base[key] = alpha * target + (1 - alpha) * base[key]

        # 추후 Weights 스키마도 수정 필요
        return Weights(safety=base["safety"], slope=base["comfort"])
