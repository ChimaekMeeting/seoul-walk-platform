import networkx as nx
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_MakePoint, ST_SetSRID, ST_X, ST_Y
from sqlalchemy import select

from src.database.postgresql import get_postgresql_db
from src.entity.network.walk_edge import WalkEdge
from src.entity.network.walk_node import WalkNode
from src.repository.layer.route_poi_repository import RoutePoiRepository

import logging
logger = logging.getLogger(__name__)


class GraphRepository:
    EDGE_TAG_FIELDS = (
        ("raw_is_tunnel", "tunnel"),
        ("raw_is_bridge", "bridge"),
        ("raw_is_overpass", "overpass"),
        ("raw_is_crosswalk", "crosswalk"),
        ("raw_is_elevated", "elevated"),
        ("raw_is_subway_network", "subway_network"),
        ("raw_is_park_green", "park_green"),
        ("raw_is_building_inside", "building_inside"),
    )

    @classmethod
    def _edge_attributes(
        cls,
        row,
        poi_counts: dict[str, int] | None = None,
    ) -> dict | None:
        """
        WalkEdge 조회 결과를 NetworkX edge 속성으로 변환합니다.

        보행 불가 LINK는 원본 DB에는 보존하되 라우팅 그래프에는 넣지 않습니다.
        `underground`처럼 원본에서 확정할 수 없는 의미는 임의로 만들지 않습니다.
        """
        if not row.is_walkable:
            return None

        tags = [
            tag
            for field_name, tag in cls.EDGE_TAG_FIELDS
            if bool(getattr(row, field_name))
        ]

        attributes = {
            "link_id": row.link_id,
            "length": row.length_m,
            "raw_link_type_code": row.raw_link_type_code,
            "is_walkable": row.is_walkable,
            "safety_score": row.safety_score,
            "nature_score": row.nature_score,
            "slope_score": row.slope_score,
            "running_score": row.running_score,
            "landmark_score": row.landmark_score,
            "child_score": row.child_score,
            "park_overlap_ratio": row.park_overlap_ratio,
            "convenience_score": row.convenience_score,
            "is_school_zone": bool(row.is_school_zone),
            "is_vehicle_caution": bool(row.is_vehicle_caution),
            "toilet_count": 0,
            "transit_count": 0,
            "accessibility_poi_count": 0,
            "tags": tags,
        }
        if poi_counts:
            attributes.update(poi_counts)
        attributes.update(
            {
                field_name: bool(getattr(row, field_name))
                for field_name, _ in cls.EDGE_TAG_FIELDS
            }
        )
        return attributes

    @staticmethod
    def load_graph() -> nx.Graph:
        from src.route_engine.engines.path_utils import PathUtils
        """
        walk_nodes + walk_edges를 PostGIS에서 읽어 NetworkX 그래프로 반환.

        Returns:
            G: Graph
                - node 속성: node_type, is_underground, is_overpass, x(lon), y(lat)
                - edge 속성: link_id, length, raw_link_type_code, is_walkable,
                             원본 LINK 플래그, tags, 각 score
        """
        G = nx.Graph()
        poi_counts_by_edge = RoutePoiRepository.get_connected_counts_by_edge()

        with get_postgresql_db() as db:
            node_rows = db.execute(
                select(
                    WalkNode.node_id,
                    WalkNode.node_type,
                    WalkNode.is_underground,
                    WalkNode.is_overpass,
                    ST_X(WalkNode.geom).label("lon"),
                    ST_Y(WalkNode.geom).label("lat"),
                )
            ).fetchall()

            for row in node_rows:
                G.add_node(
                    row.node_id,
                    lon=row.lon,
                    lat=row.lat,
                    node_type=row.node_type,
                    is_underground=row.is_underground,
                    is_overpass=row.is_overpass,
                )

            edge_rows = db.execute(
                select(
                    WalkEdge.link_id,
                    WalkEdge.start_node,
                    WalkEdge.end_node,
                    WalkEdge.length_m,
                    WalkEdge.raw_link_type_code,
                    WalkEdge.is_walkable,
                    WalkEdge.raw_is_tunnel,
                    WalkEdge.raw_is_bridge,
                    WalkEdge.raw_is_overpass,
                    WalkEdge.raw_is_crosswalk,
                    WalkEdge.raw_is_elevated,
                    WalkEdge.raw_is_subway_network,
                    WalkEdge.raw_is_park_green,
                    WalkEdge.raw_is_building_inside,
                    WalkEdge.safety_score,
                    WalkEdge.nature_score,
                    WalkEdge.slope_score,
                    WalkEdge.running_score,
                    WalkEdge.landmark_score,
                    WalkEdge.child_score,
                    WalkEdge.park_overlap_ratio,
                    WalkEdge.convenience_score,
                    WalkEdge.is_school_zone,
                    WalkEdge.is_vehicle_caution,
                ).where(WalkEdge.is_walkable.is_(True))
            ).fetchall()

            for row in edge_rows:
                attributes = GraphRepository._edge_attributes(
                    row,
                    poi_counts_by_edge.get(row.link_id),
                )
                if attributes is None:
                    continue
                G.add_edge(
                    row.start_node,
                    row.end_node,
                    **attributes,
                )

        logger.info(f"그래프 로드 완료: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        if G.number_of_nodes() == 0:
            logger.info("  ⚠️  walk_edges 데이터 없음. 빈 그래프로 초기화합니다.")
            return G

        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        G = PathUtils(G).remove_dead_ends()
        logger.info(f"최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        return G

    @staticmethod
    def load_graph_near(lat: float, lon: float, radius_m: float = 3000) -> nx.Graph:
        """
        특정 위치 반경 내 노드/엣지만 로드합니다. 전체 로드보다 빠릅니다.

        Args:
            lat      : 중심점 위도.
            lon      : 중심점 경도.
            radius_m : 검색 반경 (미터). 기본값 3,000.

        Returns:
            nx.Graph: 반경 내 노드/엣지로 구성된 NetworkX 그래프.
        """
        G = nx.Graph()
        poi_counts_by_edge = RoutePoiRepository.get_connected_counts_by_edge()
        origin_geog = ST_SetSRID(ST_MakePoint(lon, lat), 4326).cast(Geography)

        with get_postgresql_db() as db:
            node_rows = db.execute(
                select(
                    WalkNode.node_id,
                    WalkNode.node_type,
                    WalkNode.is_underground,
                    WalkNode.is_overpass,
                    ST_X(WalkNode.geom).label("lon"),
                    ST_Y(WalkNode.geom).label("lat"),
                ).where(ST_DWithin(WalkNode.geom.cast(Geography), origin_geog, radius_m))
            ).fetchall()

            for row in node_rows:
                G.add_node(
                    row.node_id,
                    lon=row.lon,
                    lat=row.lat,
                    node_type=row.node_type,
                    is_underground=row.is_underground,
                    is_overpass=row.is_overpass,
                )

            edge_rows = db.execute(
                select(
                    WalkEdge.link_id,
                    WalkEdge.start_node,
                    WalkEdge.end_node,
                    WalkEdge.length_m,
                    WalkEdge.raw_link_type_code,
                    WalkEdge.is_walkable,
                    WalkEdge.raw_is_tunnel,
                    WalkEdge.raw_is_bridge,
                    WalkEdge.raw_is_overpass,
                    WalkEdge.raw_is_crosswalk,
                    WalkEdge.raw_is_elevated,
                    WalkEdge.raw_is_subway_network,
                    WalkEdge.raw_is_park_green,
                    WalkEdge.raw_is_building_inside,
                    WalkEdge.safety_score,
                    WalkEdge.nature_score,
                    WalkEdge.slope_score,
                    WalkEdge.running_score,
                    WalkEdge.landmark_score,
                    WalkEdge.child_score,
                    WalkEdge.park_overlap_ratio,
                    WalkEdge.convenience_score,
                    WalkEdge.is_school_zone,
                    WalkEdge.is_vehicle_caution,
                ).where(
                    ST_DWithin(WalkEdge.geom.cast(Geography), origin_geog, radius_m),
                    WalkEdge.is_walkable.is_(True),
                )
            ).fetchall()

            for row in edge_rows:
                attributes = GraphRepository._edge_attributes(
                    row,
                    poi_counts_by_edge.get(row.link_id),
                )
                if attributes is None:
                    continue
                G.add_edge(
                    row.start_node,
                    row.end_node,
                    **attributes,
                )

        logger.info(f"반경 {radius_m}m 그래프 로드: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        if G.number_of_nodes() == 0:
            return G

        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        logger.info(f"최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        return G
