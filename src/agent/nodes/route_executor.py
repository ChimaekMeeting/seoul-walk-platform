import logging

from src.schema.prewalk_schema import State, FeatureTag
from src.interfaces.schema.walk_schema import WalkMode, Coordinate, PlaceLabel, WalkRouteStatus
from src.agent.tools.route_tools import RouteTool
from src.schema.route_schema import Weights
from src.repository.user.user_preference_repository import UserPreferenceRepository
from src.config.logging import log_unexpected_error

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
        # 예외0. 최단경로(oneway_shortest) 모드에서 이미 state에 경로를 채워둔 경우, 바로 state 반환
        if (
            state.mode == WalkMode.ONEWAY_SHORTEST
            and state.route_result
            and state.route_result[0].status == WalkRouteStatus.SUCCESS
        ):
            logger.info("route_executor_reuse_precomputed_shortest_route")
            return state

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
                # 이름(address, place_name)은 경로 생성에 쓰이지 않고 경로 기록에만 저장한다(#520) —
                # 프론트가 이력 화면마다 Kakao API로 좌표를 이름으로 바꾸지 않아도 되게 한다.
                if v.get("address") or v.get("place_name"):
                    args[f"{k}_label"] = PlaceLabel(address=v.get("address"), place_name=v.get("place_name"))
            elif k == "waypoints":
                args[k] = [Coordinate(lat=wp["lat"], lon=wp["lon"]) for wp in v]
            else:
                args[k] = v

        if legs is not None:
            args["leg_modes"]     = [leg["mode"] for leg in legs]
            args["leg_target_km"] = [leg.get("target_km") for leg in legs]

        args["access_token"]   = state.access_token or ""
        # 설문을 사용자 기본값으로 삼고 이번 대화 선호와 섞는다. 조회·계산은 한 번만 한다.
        preference = UserPreferenceRepository.get_by_user_id(state.user_id)
        weights = self._build_weights(state, preference=preference)
        args["custom_weights"] = weights
        # waypoint 모드만 안전·편안 가중 연결을 쓴다(#445). 다른 모드의 도구는 이
        # 인자를 받지 않으므로 넣지 않는다. _build_weights가 이미 concrete한 safety/
        # comfort 값을 만들어주므로(챗봇 경로엔 "선호 없음" 상태가 없음) 그대로 재사용한다.
        if tool_name == MODE_TOOL_MAP.get(WalkMode.WAYPOINT):
            args["preference"] = weights

        logger.info(f"mode: {state.mode}")

        # 경로 생성
        try:
            state.route_result = await self.route_tool.tool_map[tool_name].ainvoke(args)
        except Exception as exc:
            # 예외2. 경로 생성에 실패한 경우
            log_unexpected_error(logger, "route_executor_error", exc)
            return state

        return state

    def _build_weights(self, state: State, preference=None) -> Weights:
        """
        safety/comfort 두 feature에 대해 온보딩 설문 값과 state.feature_labels의
        EMA 블렌딩으로 가중치를 누적하여 반환합니다.

        preference를 넘기지 않으면 직접 조회합니다.
        """
        # 온보딩[장기] 가중치가 없는 경우를 대비해, route_schema.Weights의 기본값(SSOT)으로 초기화
        if preference is None:
            preference = UserPreferenceRepository.get_by_user_id(state.user_id)
        base = Weights().model_dump()

        # 온보딩[장기] 가중치 로드
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

        return Weights(safety=base["safety"], comfort=base["comfort"])
