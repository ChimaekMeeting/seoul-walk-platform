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
    @staticmethod
    def _edge_attributes(row, poi_counts: dict[str, int] | None = None) -> dict:
        attributes = {
            "link_id": row.link_id,
            "length": row.length_m,
            "toilet_count": 0,
            "transit_count": 0,
            "accessibility_poi_count": 0,
        }
        if poi_counts:
            attributes.update(poi_counts)
        return attributes

    @staticmethod
    def load_graph() -> nx.Graph:
        from src.route_engine.engines.path_utils import PathUtils
        """
        walk_nodes + walk_edges를 PostGIS에서 읽어 NetworkX 그래프로 반환.

        Returns:
            G: Graph
                - node 속성: x(lon), y(lat)
                - edge 속성: link_id, length
        """
        G = nx.Graph()
        poi_counts_by_edge = RoutePoiRepository.get_connected_counts_by_edge()

        with get_postgresql_db() as db:
            node_rows = db.execute(
                select(
                    WalkNode.node_id,
                    ST_X(WalkNode.geom).label("lon"),
                    ST_Y(WalkNode.geom).label("lat"),
                )
            ).fetchall()

            for row in node_rows:
                G.add_node(row.node_id, lon=row.lon, lat=row.lat)

            edge_rows = db.execute(
                select(
                    WalkEdge.link_id,
                    WalkEdge.start_node,
                    WalkEdge.end_node,
                    WalkEdge.length_m,
                )
            ).fetchall()

            for row in edge_rows:
                attributes = GraphRepository._edge_attributes(
                    row, poi_counts_by_edge.get(row.link_id)
                )
                G.add_edge(row.start_node, row.end_node, **attributes)

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
        G = nx.Graph()
        poi_counts_by_edge = RoutePoiRepository.get_connected_counts_by_edge()
        origin_geog = ST_SetSRID(ST_MakePoint(lon, lat), 4326).cast(Geography)

        with get_postgresql_db() as db:
            node_rows = db.execute(
                select(
                    WalkNode.node_id,
                    ST_X(WalkNode.geom).label("lon"),
                    ST_Y(WalkNode.geom).label("lat"),
                ).where(ST_DWithin(WalkNode.geom.cast(Geography), origin_geog, radius_m))
            ).fetchall()

            for row in node_rows:
                G.add_node(row.node_id, lon=row.lon, lat=row.lat)

            edge_rows = db.execute(
                select(
                    WalkEdge.link_id,
                    WalkEdge.start_node,
                    WalkEdge.end_node,
                    WalkEdge.length_m,
                ).where(ST_DWithin(WalkEdge.geom.cast(Geography), origin_geog, radius_m))
            ).fetchall()

            for row in edge_rows:
                attributes = GraphRepository._edge_attributes(
                    row, poi_counts_by_edge.get(row.link_id)
                )
                G.add_edge(row.start_node, row.end_node, **attributes)

        logger.info(f"반경 {radius_m}m 그래프 로드: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        if G.number_of_nodes() == 0:
            return G

        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        logger.info(f"최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        return G
