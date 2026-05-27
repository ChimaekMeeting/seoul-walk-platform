import networkx as nx
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_DWithin, ST_MakePoint, ST_SetSRID, ST_X, ST_Y
from sqlalchemy import select

from src.database.postgresql import get_postgresql_db
from src.entity.walk_network import WalkEdge, WalkNode
from src.route_engine.path_utils import remove_dead_ends


class GraphRepository:
    @staticmethod
    def load_graph() -> nx.Graph:
        """
        walk_nodes + walk_edges를 PostGIS에서 읽어 NetworkX 그래프로 반환.

        Returns:
            G: Graph
                - node 속성: node_type, is_underground, is_overpass, x(lon), y(lat)
                - edge 속성: link_id, length, road_type, path_type,
                             safety_score, nature_score, slope_score
        """
        G = nx.Graph()

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
                    x=row.lon,
                    y=row.lat,
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
                    WalkEdge.road_type,
                    WalkEdge.path_type,
                    WalkEdge.safety_score,
                    WalkEdge.nature_score,
                    WalkEdge.slope_score,
                )
            ).fetchall()

            for row in edge_rows:
                G.add_edge(
                    row.start_node,
                    row.end_node,
                    link_id=row.link_id,
                    length=row.length_m,
                    road_type=row.road_type,
                    path_type=row.path_type,
                    safety_score=row.safety_score,
                    nature_score=row.nature_score,
                    slope_score=row.slope_score,
                )

        print(f"그래프 로드 완료: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        G = remove_dead_ends(G)
        print(f"최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

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
                    x=row.lon,
                    y=row.lat,
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
                    WalkEdge.road_type,
                    WalkEdge.path_type,
                    WalkEdge.safety_score,
                    WalkEdge.nature_score,
                    WalkEdge.slope_score,
                ).where(ST_DWithin(WalkEdge.geom.cast(Geography), origin_geog, radius_m))
            ).fetchall()

            for row in edge_rows:
                G.add_edge(
                    row.start_node,
                    row.end_node,
                    link_id=row.link_id,
                    length=row.length_m,
                    road_type=row.road_type,
                    path_type=row.path_type,
                    safety_score=row.safety_score,
                    nature_score=row.nature_score,
                    slope_score=row.slope_score,
                )

        print(f"반경 {radius_m}m 그래프 로드: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        print(f"최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        return G
