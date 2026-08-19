import logging

from src.schema.prewalk_schema import State
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

# 테마·설문이 없을 때의 기본 가중치(baseline).
# route_schema.Weights 기본값을 단일 출처(SSOT)로 사용함.
#   (안전/평지 0.5, 미관·활동·동반 0.0 → 일반 경로 = 해당 특성 무편향)
_BASELINE_WEIGHTS = Weights().model_dump()

# 대화 테마(state.themes)를 가중치에 반영하는 EMA 블렌딩 강도(0~1)와 목표값.
# base[key] = alpha * _THEME_TARGET + (1 - alpha) * base[key] — 클수록 테마가 base를 더 세게 끌어당김.
# TODO(임시): TAG_WEIGHT_MAP은 "이 테마가 어떤 축에 영향을 주는지"(키 집합)만 참고하고
# delta 값 자체는 쓰지 않음 — 모든 축이 같은 고정 target으로 끌려감(태그별 크기 구분 없음).
# 추후 delta/weights 체계를 한 번에 다시 설계할 때 함께 정리 예정.
_THEME_EMA_ALPHA  = 0.6
_THEME_TARGET     = 1.0

_ACCESSIBLE_THEMES = {"유모차", "계단이 불편한"}
_CONVENIENT_THEMES = {"활기찬", "힙한"}

class RouteExecutor:
    def __init__(self):
        from src.interfaces.dependencies import get_gps_art_service
        self.route_tool = RouteTool(get_gps_art_service())

    async def run(self, state: State) -> State:
        """
        UserPreference와 테마 태그를 반영한 가중치로 경로를 생성합니다.
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
        profile = self._select_profile(state)
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

    @staticmethod
    def _select_profile(state: State) -> ScoringProfile:
        """명시 프로필을 우선하고, 없으면 대화 테마에서 결정합니다."""
        if state.profile is not None:
            return state.profile
        themes = set(state.themes)
        if themes & _ACCESSIBLE_THEMES:
            return ScoringProfile.ACCESSIBLE
        if themes & _CONVENIENT_THEMES:
            return ScoringProfile.CONVENIENT
        return ScoringProfile.DEFAULT

    def _build_weights(
        self,
        state: State,
        profile: ScoringProfile = ScoringProfile.DEFAULT,
    ) -> Weights:
        """
        UserPreference base weights에 state.themes의 delta를 합산해 최종 Weights를 반환합니다.
        UserPreference가 없으면 _BASELINE_WEIGHTS를 사용합니다.
        (안전/평지는 0.5, 미관·활동·동반 특성은 0.0 → 일반 경로는 해당 특성 무편향)
        """
        from src.service.user.survey_service import TAG_WEIGHT_MAP  # 순환 import 방지(지연 로드)

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

        # 테마는 EMA 블렌딩으로 반영. TAG_WEIGHT_MAP의 delta 값은 쓰지 않고, 이 테마가
        # 건드리는 축(key)인지만 참고해 고정된 _THEME_TARGET 쪽으로 alpha만큼 끌어당김
        # (임시 방식, 위 TODO 참고).
        for tag in state.themes:
            for key in TAG_WEIGHT_MAP.get(tag, {}):
                base[key] = _THEME_EMA_ALPHA * _THEME_TARGET + (1 - _THEME_EMA_ALPHA) * base[key]

        weights = Weights(**base)
        return weights
