import logging

from src.schema.prewalk_schema import State, FeatureTag
from src.interfaces.schema.walk_schema import WalkMode, Coordinate
from src.agent.tools.route_tools import RouteTool
from src.schema.route_schema import SafetyComfortPreference, Weights
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

# _build_weights(preference=...)의 "안 넘김" 표식. None은 "선호 행이 없음"이라는
# 유효한 값이라 기본값으로 쓸 수 없다.
_FETCH_PREFERENCE = object()

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
            args["leg_target_km"] = [leg.get("target_km") for leg in legs]

        args["access_token"]   = state.access_token or ""
        profile = state.profile or ScoringProfile.DEFAULT
        state.profile = profile
        args["profile"] = profile
        # 설문을 사용자 기본값으로 삼고 이번 대화 선호와 섞는다. 조회·계산은 한 번만 한다.
        preference = UserPreferenceRepository.get_by_user_id(state.user_id)
        weights = self._build_weights(state, preference=preference)
        args["custom_weights"] = weights
        # waypoint 모드만 안전·편안 가중 연결을 쓴다(#445). 다른 모드의 도구는 이
        # 인자를 받지 않으므로 넣지 않는다.
        if tool_name == MODE_TOOL_MAP.get(WalkMode.WAYPOINT):
            args["preference"] = self._build_preference_signal(weights)

        logger.info(f"mode: {state.mode}")
        logger.info(f"custom_weights: {args['custom_weights']}")
        logger.info(f"preference: {args.get('preference')}")

        # 경로 생성
        try:
            state.route_result = await self.route_tool.tool_map[tool_name].ainvoke(args)
        except Exception:
            # 예외2. 경로 생성에 실패한 경우
            logger.exception("경로 생성에 실패했습니다.")
            return state

        return state

    def _build_weights(self, state: State, preference=_FETCH_PREFERENCE) -> Weights:
        """
        safety/comfort 두 feature에 대해 온보딩 설문 값과 state.feature_labels의
        EMA 블렌딩으로 가중치를 누적하여 반환합니다.

        preference를 넘기면 다시 조회하지 않습니다. 넘기지 않으면 직접 조회합니다.
        """
        if preference is _FETCH_PREFERENCE:
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

        return Weights(safety=base["safety"], slope=base["comfort"])

    @staticmethod
    def _build_preference_signal(weights: Weights) -> SafetyComfortPreference:
        """설문·프로필 기본값과 대화 선호를 섞은 결과를 가중 연결에 전달한다.

        기본값도 서비스가 사용하는 선호다. 출처가 설문/이번 발화인지로 축을 끄거나
        0으로 바꾸지 않는다. 기존 _build_weights의 혼합 계산 결과를 그대로 사용한다.
        """
        return SafetyComfortPreference(safety=weights.safety, comfort=weights.slope)
