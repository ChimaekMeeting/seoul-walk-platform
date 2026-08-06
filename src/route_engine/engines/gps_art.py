import logging
import math
from typing import List

import networkx as nx

from src.interfaces.schema.walk_schema import (
    WalkMode,
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint import WaypointComposerEngine
from src.schema.route_schema import (
    GpsArtPoint,
    GpsArtRouteInput,
    WaypointCoordinate,
    WaypointRouteInput,
)

logger = logging.getLogger(__name__)

_KM_PER_DEG_LAT: float = 111.32  # 위도 1도당 거리(km) 근사값
_NETWORK_FACTOR: float = 1.4     # 직선 거리 -> 도로망 거리 추정 계수. path_utils.est_network_dist와 동일 기준


class GpsArtEngine:
    """
    정규화된 도형 좌표(shape_points)를 실제 위경도로 변환하고 그래프 노드로 스냅한 뒤,
    WaypointComposerEngine으로 순서대로 최단 경로 연결해 GPS Art 경로를 생성한다.
    """

    def __init__(self, inp: GpsArtRouteInput, G: nx.Graph):
        self.inp   = inp
        # 그래프를 직접 mutate하지 않고 WaypointComposerEngine에 그대로 넘기기만 하므로 복사가 필요 없다.
        self.G     = G
        self.utils = PathUtils(self.G)

    def run(self) -> List[WalkRouteResponse]:
        """
        GPS Art 경로를 생성합니다.
        """
        logger.info(
            "GPS Art 경로 생성 엔진을 시작합니다: points=%d, target_km=%s",
            len(self.inp.shape_points), self.inp.target_km,
        )

        try:
            geo_points = self._map_to_geo(self.inp.shape_points)
        except ValueError as e:
            logger.warning("도형 좌표 변환에 실패했습니다: %s", e)
            return [WalkRouteResponse(status=WalkRouteStatus.NO_PATH, mode=WalkMode.GPS_ART, coordinates=[], total_km=0.0)]

        snapped = self._snap_to_nodes(geo_points)
        if len(snapped) < 2:
            logger.warning("그래프에 스냅된 노드가 2개 미만입니다: %d개", len(snapped))
            return [WalkRouteResponse(status=WalkRouteStatus.NO_PATH, mode=WalkMode.GPS_ART, coordinates=[], total_km=0.0)]

        waypoint_inp = self._build_waypoint_input(snapped)
        composer = WaypointComposerEngine(waypoint_inp, self.G)
        results = composer.run()
        results[0].mode = WalkMode.GPS_ART  # WaypointComposerEngine은 mode=WAYPOINT로 채우므로 덮어씀
        return results

    def _map_to_geo(self, shape_points: List[GpsArtPoint]) -> list[tuple[float, float]]:
        """
        도형 좌표(로컬 단위, 단위 없음) -> 실제 위경도로 변환합니다.
        1) 도형의 직선 둘레(로컬 단위 합)를 구한다.
        2) target_km(도로망 기준 목표 거리)을 도로망 계수로 나눠 "직선 기준" 목표 둘레를 구한다.
        3) 두 값의 비율로 scale(로컬 단위 -> km)을 계산해 각 점에 적용한다.
        4) origin을 중심으로 위경도 오프셋을 더한다(x=동서, y=남북).
        """
        # 도형 둘레 계산
        local_perimeter = sum(
            math.hypot(b.x - a.x, b.y - a.y)  # 유클리드 거리: 점a에서 점b까지의 거리
            for a, b in zip(shape_points, shape_points[1:])
        )
        if local_perimeter <= 0:
            raise ValueError("도형 좌표의 둘레가 0입니다(모든 점이 같은 위치)")

        straight_line_target_km = self.inp.target_km / _NETWORK_FACTOR
        scale = straight_line_target_km / local_perimeter  # km per 로컬 단위

        lat_km_per_deg = _KM_PER_DEG_LAT
        lon_km_per_deg = _KM_PER_DEG_LAT * math.cos(math.radians(self.inp.origin_lat))

        geo_points = []
        for p in shape_points:
            dx_km = p.x * scale
            dy_km = p.y * scale
            lat = self.inp.origin_lat + dy_km / lat_km_per_deg
            lon = self.inp.origin_lon + dx_km / lon_km_per_deg
            geo_points.append((lat, lon))
        return geo_points

    def _snap_to_nodes(self, geo_points: list[tuple[float, float]]) -> list[int]:
        """
        각 위경도를 그래프 최근접 노드로 스냅합니다.
        연속으로 같은 노드에 스냅되면(도로망이 성긴 구간에서 꼭짓점이 뭉개지는 경우) 하나로 합칩니다.
        """
        snapped: list[int] = []
        for lat, lon in geo_points:
            node = self.utils.find_nearest_node(lat, lon)
            if node is None:
                continue
            if snapped and snapped[-1] == node:
                continue
            snapped.append(node)
        return snapped

    def _build_waypoint_input(self, snapped: list[int]) -> WaypointRouteInput:
        """
        스냅된 노드열을 WaypointComposerEngine 입력으로 변환합니다.
        모든 leg는 도형 왜곡을 막기 위해 oneway_shortest만 사용합니다.
        """
        coords = [(self.G.nodes[n]["lat"], self.G.nodes[n]["lon"]) for n in snapped]
        start_lat, start_lon = coords[0]
        end_lat, end_lon     = coords[-1]
        middle                = coords[1:-1]
        leg_count             = len(snapped) - 1

        return WaypointRouteInput(
            start_lat=start_lat,
            start_lon=start_lon,
            end_lat=end_lat,
            end_lon=end_lon,
            waypoints=[WaypointCoordinate(lat=lat, lon=lon) for lat, lon in middle],
            leg_modes=["oneway_shortest"] * leg_count,
            leg_target_km=[None] * leg_count,
        )