import logging
from typing import Optional, List

import networkx as nx

from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.walk_schema import (
    Coordinate,
    RoutePoiItem,
    WalkMode,
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.repository.user.route_history_repository import RouteHistoryRepository
from src.repository.user.user_repository import UserRepository
from src.repository.layer.route_poi_repository import RoutePoiRepository
from src.route_engine.engines import (
    GpsArtEngine,
    OnewayAstarEngine,
    WaypointComposerEngine,
)
from src.route_engine.engines.circular_grasp_waypoint_alns import CircularGraspWaypointAlnsEngine
from src.route_engine.engines.oneway_grasp_waypoint_alns import OnewayGraspWaypointAlnsEngine
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.weighted_cost_runtime import build_request_cost_context
from src.config.settings import settings
from src.schema.route_schema import (
    CircularRouteInput,
    GpsArtPoint,
    GpsArtRouteInput,
    OnewayRouteInput,
    WaypointCoordinate,
    WaypointLegMode,
    WaypointRouteInput,
    Weights,
)
from src.service.user.auth_service import AuthService
from src.config.logging import log_unexpected_error

logger = logging.getLogger(__name__)

# 후보 경로를 다양화하는 엔진이 보장하는 경로 개수(대표 경로 1 + 후보 경로 2 = 3). 이름과 달리
# 후보 경로만의 개수가 아니라 대표 경로를 포함한 candidate_features 전체 길이다. circular_random
# (CircularGraspWaypointAlnsEngine)과 oneway_random(OnewayGraspWaypointAlnsEngine,
# 2026-09-20, #498 확장)은 둘 다 MULTI_CANDIDATE_COMBOS(construction="grasp",
# refinement="alns")에 속해 이 개수를 만족한다. 장기 프로필(안전/편안 SGD 갱신)은 후보 경로가
# 1개 이상이면 대조값(contrast)을 쓰고 0개면 별점만 쓴다(#516, longterm_profile_service).
MIN_CANDIDATES_FOR_PROFILE = 3


class RouteService:
    def __init__(self, G: nx.Graph, auth_service: AuthService):
        self.G = G
        self.auth_service = auth_service

        self.base_engines: dict = {
            WalkMode.CIRCULAR_RANDOM: CircularGraspWaypointAlnsEngine,
            WalkMode.ONEWAY_SHORTEST: OnewayAstarEngine,
            WalkMode.ONEWAY_RANDOM: OnewayGraspWaypointAlnsEngine,
            WalkMode.GPS_ART: GpsArtEngine,
            WalkMode.WAYPOINT: WaypointComposerEngine,
        }

    def get_route(
        self,
        access_token: str,
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None,
        mode: WalkMode = WalkMode.CIRCULAR_RANDOM,
        custom_weights: Optional[Weights] = None,
        shape_points: Optional[List[GpsArtPoint]] = None,
        waypoints: Optional[List[Coordinate]] = None,
        leg_modes: Optional[List[WaypointLegMode]] = None,
        leg_target_km: Optional[List[Optional[float]]] = None,
        preference: Optional[Weights] = None,
        seed: Optional[int] = None,
    ) -> List[WalkRouteResponse]:
        """
        context에 적합한 경로 생성 엔진을 호출합니다.
        mode는 경로 생성 방식(circular_random/oneway_shortest/oneway_random/gps_art/waypoint)을 결정합니다.
        shape_points는 gps_art 모드 전용이며, 호출 전에 이미 도형 이름 -> 좌표 변환이
        끝난 상태여야 합니다(RouteService는 이미지 생성 등 비동기 작업을 하지 않음).
        waypoints/leg_modes/leg_target_km은 waypoint 모드 전용이다. leg_modes[i]/leg_target_km[i]는
        origin -> waypoints[0] -> ... -> destination 순서상 i번째 구간의 이동 방식이며,
        지정하지 않은 구간은 최단 경로(oneway_shortest)로 채워진다.
        """
        logger.info(
            "walk route request: mode=%s has_destination=%s",
            mode,
            destination is not None,
        )

        auth_status, provider, provider_id = self.auth_service.check_access_token(access_token)
        if auth_status != Status.SUCCESS:
            logger.warning("walk route auth failed: mode=%s status=%s", mode, auth_status.value)
            return [WalkRouteResponse(
                status=WalkRouteStatus(auth_status.value),
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )]

        if mode not in self.base_engines:
            logger.warning("walk route unknown mode: mode=%s", mode)
            return [WalkRouteResponse(
                status=WalkRouteStatus.UNKNOWN_ERROR,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )]

        utils = PathUtils(self.G)
        if utils.find_nearest_node_with_expansion(origin.lat, origin.lon) is None:
            logger.warning("walk route no nearest start node: mode=%s", mode)
            return [WalkRouteResponse(
                status=WalkRouteStatus.NO_NEAREST_START_NODE,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )]

        if mode != WalkMode.CIRCULAR_RANDOM and destination is not None:
            end_node = utils.find_nearest_node_with_expansion(destination.lat, destination.lon)
            if end_node is None:
                logger.warning("walk route no nearest end node: mode=%s", mode)
                return [WalkRouteResponse(
                    status=WalkRouteStatus.NO_NEAREST_END_NODE,
                    mode=mode,
                    coordinates=[],
                    total_km=0.0,
                )]

        if mode == WalkMode.WAYPOINT and waypoints:
            for wp in waypoints:
                if utils.find_nearest_node_with_expansion(wp.lat, wp.lon) is None:
                    logger.warning("walk route no nearest waypoint node: mode=%s", mode)
                    return [WalkRouteResponse(
                        status=WalkRouteStatus.NO_NEAREST_END_NODE,
                        mode=mode,
                        coordinates=[],
                        total_km=0.0,
                    )]

        try:
            engine = self._build_engine(
                mode, origin, destination, target_km, custom_weights, shape_points,
                waypoints, leg_modes, leg_target_km, preference, seed,
            )
        except ValueError:
            logger.warning("walk route invalid destination: mode=%s", mode)
            return [WalkRouteResponse(
                status=WalkRouteStatus.INVALID_DESTINATION,
                mode=mode,
                coordinates=[],
                total_km=0.0,
            )]

        logger.info("walk route engine selected: mode=%s engine=%s", mode, type(engine).__name__)

        results = engine.run()
        if mode == WalkMode.ONEWAY_RANDOM:
            # 편도 우회는 preference가 실제 cost context로 만들어졌는지를
            # 응답에도 남긴다. 챗봇과 직접 API의 경로 품질을 구분할 수 있어야 한다.
            weighted = bool(getattr(getattr(engine, "cost_cache", None), "cost_context", None))
            cost_context = getattr(getattr(engine, "cost_cache", None), "cost_context", None)
            skipped_reason = None
            if not weighted:
                if preference is None:
                    skipped_reason = "no_preference"
                elif (preference.safety, preference.comfort) == (0.0, 0.0):
                    skipped_reason = "zero_weights"
                else:
                    skipped_reason = "scores_unavailable"
            for result in results:
                result.preference_applied = weighted
                result.preference_skipped_reason = skipped_reason
                if cost_context is not None:
                    result.cost_alpha = cost_context.alpha
                    result.cost_beta = cost_context.beta
        # circular_random/oneway_random은 최대 3개까지 다양화한 후보를 반환한다.
        # 앱은 어느 후보든 바로 선택해 산책·즐겨찾기·평가할 수 있으므로 성공 후보마다
        # RouteHistory를 하나씩 저장해 각각의 id를 응답에 붙인다. 후보별 history에는 해당
        # 후보 특성을 index 0으로 재정렬해 저장한다 — longterm_profile_service가 index 0을
        # 실제 선택 경로(X_R)로 해석하기 때문이다.
        first_result = results[0]
        logger.info(
            "walk route result: mode=%s status=%s candidates=%d",
            mode, first_result.status.value, len(results),
        )

        for result in results:
            if result.status != WalkRouteStatus.SUCCESS:
                continue
            try:
                result.nearby_pois = [
                    RoutePoiItem.model_validate(poi)
                    for poi in RoutePoiRepository.find_near_route(
                        result.coordinates
                    )
                ]
            except Exception as exc:
                log_unexpected_error(logger, "route_poi_lookup_error", exc)

        if first_result.status == WalkRouteStatus.SUCCESS:
            try:
                user = UserRepository.find_by_provider_and_provider_id(provider, provider_id)
                if user is not None:
                    # engine.candidate_feature_vectors: results와 같은 순서의 {"safety","comfort"}
                    # 경로(대표 경로, 후보 경로)별 평균 — 장기 프로필 SGD가 나중에 X_R/X_contrast로 쓴다
                    # (route_feedback). 다양화를 지원하지 않는 엔진(oneway_shortest 등)은 속성 자체가
                    # 없을 수 있다(후보 경로 0개).
                    candidate_features = getattr(engine, "candidate_feature_vectors", None) or None
                    if candidate_features and len(candidate_features) < MIN_CANDIDATES_FOR_PROFILE:
                        logger.info(
                            "walk route has fewer candidate routes than expected: mode=%s candidate_routes=%d",
                            mode, len(candidate_features) - 1,
                        )

                    for index, result in enumerate(results):
                        if result.status != WalkRouteStatus.SUCCESS:
                            continue

                        selected_first_features = candidate_features
                        if candidate_features and index < len(candidate_features):
                            selected_first_features = [
                                candidate_features[index],
                                *candidate_features[:index],
                                *candidate_features[index + 1:],
                            ]

                        history = RouteHistoryRepository.save(
                            user_id=user.id,
                            mode=mode,
                            origin_lat=origin.lat,
                            origin_lon=origin.lon,
                            coordinates=result.coordinates,
                            total_km=result.total_km,
                            destination_lat=destination.lat if destination else None,
                            destination_lon=destination.lon if destination else None,
                            candidate_features=selected_first_features,
                        )
                        result.id = history.id
            except Exception as exc:
                log_unexpected_error(logger, "route_history_save_error", exc)

        return results

    def get_shortest_km(self, origin: Coordinate, destination: Coordinate) -> Optional[float]:
        """
        origin·destination 사이의 물리적 최단 거리(km)만 가볍게 구한다.

        `ONEWAY_SHORTEST`가 실제로 쓰는 것과 같은 엔진(`OnewayAstarEngine`, 거리 전용
        Haversine A*)을 직접 호출한다 — GRASP+ALNS 같은 무거운 조합 최적화(`oneway_random`,
        초 단위)를 거치지 않고 ms~수백ms 수준으로 끝난다. `custom_weights`/`cost_context`를
        넘기지 않아 항상 물리 최단(순수 거리 기준)을 반환한다 — "이 목표 거리가 최단거리보다
        짧은가"를 판단하는 용도라 가중치가 섞이면 기준 자체가 흔들린다.

        경로를 못 찾으면(출발·도착 인근 노드가 없거나 연결이 끊긴 경우) None을 반환한다.
        """
        inp = OnewayRouteInput(
            start_lat=origin.lat,
            start_lon=origin.lon,
            end_lat=destination.lat,
            end_lon=destination.lon,
        )
        result = OnewayAstarEngine(inp, self.G).run()[0]
        if result.status != WalkRouteStatus.SUCCESS:
            logger.warning(f"get_shortest_km: 최단거리를 구하지 못했습니다 (status={result.status})")
            return None
        return result.total_km

    # 가중 비용 자체는 어떤 WalkMode를 쓰는지 모른다 — preference가 있으면(그리고
    # 점수 커버리지가 충분하면) 항상 cost_context를 만든다. 이걸 실제로 엔진에
    # 넘길지는 모드별로 _build_engine()이 정한다(예: ONEWAY_SHORTEST는 #445 설계
    # 결정 A에 따라 "최단"을 물리 최단거리로 유지하려고 넘기지 않고 버린다).
    def _build_cost_context(self, preference: Optional[Weights]):
        """요청 하나가 쓸 가중 비용 객체. 해당 없으면 None(거리 전용).

        **요청당 한 번만** 만들고 그 요청의 모든 구간이 같은 객체를 공유한다.
        전역에 캐시하지 않는다 — 다른 사용자의 가중치와 섞이면 안 된다.

        preference는 챗봇에서 설문/프로필 기본값과 대화 선호를 섞은 결과인
        Weights다. 기본값도 반영하며, 직접 호출자가 신호를 생략하면(None) 거리
        기준을 쓴다.

        그래프를 훑지 않는다. 기동 때 붙여 둔 적재율·중앙값만 읽으므로 상수 시간이다.
        """
        if preference is None:
            return None

        safety, comfort = preference.safety, preference.comfort
        return build_request_cost_context(
            self.G,
            safety_preference=safety,
            slope_preference=comfort,
            weight_limit=settings.WALK_WEIGHT_LIMIT,
            accident_ratio=settings.WALK_UNSAFE_ACCIDENT_RATIO,
        )

    @staticmethod
    def _resolve_fill_leg_mode(
        given_modes: List[WaypointLegMode],
        preference: Optional[Weights],
        cost_context,
    ) -> tuple[str, Optional[str]]:
        """방식을 지정하지 않은 구간을 무엇으로 채울지와, 가중 연결을 쓰지 못한 사유.

        패딩 **전에** 판단해야 한다 — 먼저 oneway_shortest로 채워 버리면 "사용자가
        고른 최단"과 "서비스가 채운 연결"을 더 이상 구분할 수 없다.

        oneway_random 구간이 섞인 요청은 이번 가중 연결 대상에서 제외한다. 최상위
        WalkMode.ONEWAY_RANDOM은 2026-09-20(#498 확장)부터 GRASP+ALNS로 cost_context를
        쓰지만, 다중 경유지(WaypointRouteInput) 요청의 개별 leg 채움은 그와 별개로
        여기서 의도적으로 건드리지 않았다(#498 확장 범위 밖 — 구간별로 GRASP+ALNS를
        돌리면 다구간 요청의 응답 시간이 늘어나는 트레이드오프가 있어 별도 판단이 필요).
        reason 문자열 "beam_leg_present"는 원래 Beam 구간이었을 때 이름을 그대로 쓴다
        (API 응답 계약).
        """
        if "oneway_random" in given_modes:
            return "oneway_shortest", "beam_leg_present"
        if preference is None:
            return "oneway_shortest", "no_preference"
        if (preference.safety, preference.comfort) == (0.0, 0.0):
            return "oneway_shortest", "zero_weights"
        if cost_context is None:
            # 선호는 있지만 점수 커버리지가 부족해 가중 모드가 꺼져 있다.
            return "oneway_shortest", "scores_unavailable"
        return "oneway_preferred", None

    def _build_engine(
        self,
        mode: WalkMode,
        origin: Coordinate,
        destination: Optional[Coordinate] = None,
        target_km: Optional[float] = None,
        custom_weights: Optional[Weights] = None,
        shape_points: Optional[List[GpsArtPoint]] = None,
        waypoints: Optional[List[Coordinate]] = None,
        leg_modes: Optional[List[WaypointLegMode]] = None,
        leg_target_km: Optional[List[Optional[float]]] = None,
        preference: Optional[Weights] = None,
        seed: Optional[int] = None,
    ):
        """custom_weights를 엔진에 주입해 경로 생성 엔진 인스턴스를 반환합니다."""
        cost_context = self._build_cost_context(preference)

        if mode == WalkMode.CIRCULAR_RANDOM:
            inp = CircularRouteInput(
                start_lat=origin.lat,
                start_lon=origin.lon,
                target_km=target_km,
            )
            # cost_context가 있으면 경유지 확정 후 A* 연결(BuildCycleRoute)이 가중 비용을
            # 쓴다(#462). ALNS의 경유지 선택 자체(alns_search)는 거리 기준 그대로다.
            return self.base_engines[mode](
                inp, self.G, cost_context=cost_context,
                seed=seed if seed is not None else 42,
                time_budget_sec=settings.WALK_CIRCULAR_TIME_BUDGET_SEC,
            )

        if mode == WalkMode.GPS_ART:
            if not shape_points:
                raise ValueError(f"{mode} 모드에서는 shape_points가 필요합니다")
            if target_km is None:
                raise ValueError(f"{mode} 모드에서는 target_km이 필요합니다")
            inp = GpsArtRouteInput(
                shape_points=shape_points,
                origin_lat=origin.lat,
                origin_lon=origin.lon,
                target_km=target_km,
            )
            # GpsArtEngine은 내부적으로 leg마다 oneway_shortest만 써서 custom_weights를 받지 않음
            return self.base_engines[mode](inp, self.G)

        if mode == WalkMode.WAYPOINT:
            if destination is None:
                raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")

            stop_waypoints = waypoints or []
            expected_legs  = len(stop_waypoints) + 1

            given_modes = list(leg_modes or [])
            fill_mode, skipped_reason = self._resolve_fill_leg_mode(
                given_modes, preference, cost_context,
            )
            # 지정하지 않은 구간만 채운다. 사용자가 명시적으로 고른 최단 구간을
            # 저장된 선호 때문에 가중 연결로 바꾸지 않는다.
            padded_modes = given_modes + [fill_mode] * (expected_legs - len(given_modes))
            padded_target_km = list(leg_target_km or [])
            padded_target_km += [None] * (expected_legs - len(padded_target_km))

            if "oneway_random" in padded_modes or "oneway_preferred" not in padded_modes:
                cost_context = None

            inp = WaypointRouteInput(
                start_lat=origin.lat,
                start_lon=origin.lon,
                end_lat=destination.lat,
                end_lon=destination.lon,
                waypoints=[WaypointCoordinate(lat=wp.lat, lon=wp.lon) for wp in stop_waypoints],
                leg_modes=padded_modes,
                leg_target_km=padded_target_km,
            )
            return self.base_engines[mode](
                inp, self.G, custom_weights=custom_weights,
                cost_context=cost_context,
                preference_skipped_reason=skipped_reason,
                # 미합의 우회 상한은 일반 요청에서 활성화하지 않는다.
                # 실험용 인자는 테스트/벤치마크에서만 명시적으로 전달한다.
            )

        if mode == WalkMode.ONEWAY_RANDOM:
            if destination is None:
                raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")

            # GRASP+ALNS 기반 편도 우회(2026-09-20, #498 확장) — target_km에 맞춰
            # 경유지를 골라 일부러 돌아가는 "우회" 경로를 만든다. cost_context가 있으면
            # 경유지 확정 후 A* 연결이 가중 비용을 쓴다(CIRCULAR_RANDOM과 동일한 배선).
            # 분기를 ONEWAY_SHORTEST와 합치지 않은 이유는 그대로다 — 우회 로직만
            # 여기서 갈아 끼울 수 있어야 한다.
            inp = OnewayRouteInput(
                start_lat=origin.lat,
                start_lon=origin.lon,
                end_lat=destination.lat,
                end_lon=destination.lon,
                target_km=target_km,
            )
            return self.base_engines[mode](
                inp, self.G, cost_context=cost_context,
                seed=seed if seed is not None else 42,
                time_budget_sec=settings.WALK_ONEWAY_TIME_BUDGET_SEC,
            )

        if destination is None:
            raise ValueError(f"{mode} 모드에서는 destination이 필요합니다")

        inp = OnewayRouteInput(
            start_lat=origin.lat,
            start_lon=origin.lon,
            end_lat=destination.lat,
            end_lon=destination.lon,
            target_km=target_km,
        )
        return self.base_engines[mode](inp, self.G, custom_weights=custom_weights)
