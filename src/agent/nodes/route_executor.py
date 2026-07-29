import logging

from src.schema.prewalk_schema import State
from src.interfaces.schema.walk_schema import WalkMode, Coordinate
from src.agent.tools.route_tools import RouteTool
from src.schema.route_schema import Weights
from src.repository.user.user_preference_repository import UserPreferenceRepository

logger = logging.getLogger(__name__)

MODE_TOOL_MAP: dict[WalkMode, str] = {
    WalkMode.CIRCULAR_RANDOM: "circular_random_route",
    WalkMode.ONEWAY_SHORTEST: "oneway_shortest_route",
    WalkMode.ONEWAY_RANDOM:   "oneway_random_route",
}

# 테마·설문이 없을 때의 기본 가중치(baseline).
# route_schema.Weights 기본값을 단일 출처(SSOT)로 사용함.
#   (안전/평지 0.5, 미관·활동·동반 0.0 → 일반 경로 = 해당 특성 무편향)
_BASELINE_WEIGHTS = Weights().model_dump()

# 대화 테마(state.themes)를 가중치에 반영하는 강도. 설문 delta(±0.2) 대비 배수.
# baseline이 0이 된 미관 특성을 테마가 충분히 끌어올리도록 강하게 적용함.
_THEME_STRENGTH = 3.0

class RouteExecutor:
    def __init__(self):
        self.route_tool = RouteTool()

    async def run(self, state: State) -> State:
        """
        UserPreference와 테마 태그를 반영한 가중치로 경로를 생성합니다.
        """
        # 예외1. 모드와 매핑되는 경로 생성 엔진이 없는 경우
        tool_name = MODE_TOOL_MAP.get(state.mode)
        if not tool_name:
            logger.warning(f"모드와 매핑되는 경로 생성 엔진이 없습니다: mode = {state.mode}")
            return state

        args = {
            k: Coordinate(lat=v["lat"], lon=v["lon"]) if k in ("origin", "destination") else v
            for k, v in state.user_context.model_dump(exclude={"mode"}, exclude_none=True).items()
        }
        args["access_token"]   = state.access_token or ""
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
        UserPreference base weights에 state.themes의 delta를 합산해 최종 Weights를 반환합니다.
        UserPreference가 없으면 _BASELINE_WEIGHTS를 사용합니다.
        (안전/평지는 0.5, 미관·활동·동반 특성은 0.0 → 일반 경로는 해당 특성 무편향)
        """
        from src.service.user.survey_service import TAG_WEIGHT_MAP  # 순환 import 방지(지연 로드)

        preference = UserPreferenceRepository.get_by_user_id(state.user_id)
        if preference is None:
            logger.debug("UserPreference가 없어, baseline 가중치를 사용합니다.")

        # 특성별로: 설문값(있으면) 사용, 없으면 baseline 사용
        base = {
            key: (
                getattr(preference, f"weights_{key}")
                if preference and getattr(preference, f"weights_{key}") is not None
                else default
            )
            for key, default in _BASELINE_WEIGHTS.items()
        }

        # 테마 delta를 _THEME_STRENGTH 배로 적용하고, clamp를 [0.0, 1.0](스키마 전 범위)로 넓힘
        #   - 기존 (delta * 0.5 + clamp[0.1, 0.8])은 nature를 0.5→0.6 정도만 올려 효과가 미미했음
        for tag in state.themes:
            for key, delta in TAG_WEIGHT_MAP.get(tag, {}).items():
                base[key] = max(0.0, min(1.0, base[key] + delta * _THEME_STRENGTH))

        weights = Weights(**base)
        return weights
