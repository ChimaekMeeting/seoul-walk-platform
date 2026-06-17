import networkx as nx
from sqlalchemy import func, select, cast
from geoalchemy2 import Geography

from src.database.postgresql import get_postgresql_db
from src.entity.network.walk_node import WalkNode
from src.entity.network.walk_edge import WalkEdge
from src.route_engine.engines.path_utils import remove_dead_ends


class GraphRepository:
    """
    walk_nodes와 walk_edges를 읽어 NetworkX 그래프를 생성합니다.
    """

    @staticmethod
    def _node_stmt():
        """
        walk_nodes 조회용 기본 SELECT 구문을 반환합니다.
        """
        return select(
            WalkNode.node_id,
            WalkNode.node_type,
            WalkNode.is_underground,
            WalkNode.is_overpass,
            func.ST_X(WalkNode.geom).label("lon"),
            func.ST_Y(WalkNode.geom).label("lat"),
        )

    @staticmethod
    def _edge_stmt():
        """
        walk_edges 조회용 기본 SELECT 구문을 반환합니다.
        """
        return select(
            WalkEdge.link_id,
            WalkEdge.start_node,
            WalkEdge.end_node,
            WalkEdge.length_m,
            WalkEdge.safety_score,
            WalkEdge.nature_score,
            WalkEdge.slope_score,
            WalkEdge.running_score,
            WalkEdge.landmark_score,
            WalkEdge.child_score,
        )

    @staticmethod
    def _build_graph(node_rows, edge_rows) -> nx.Graph:
        """
        노드·엣지 행 목록으로 NetworkX 그래프를 생성합니다.
        """
        G = nx.Graph()
        for row in node_rows:
            G.add_node(
                row.node_id,
                lon=row.lon,
                lat=row.lat,
                node_type=row.node_type,
                is_underground=row.is_underground,
                is_overpass=row.is_overpass,
            )
        for row in edge_rows:
            G.add_edge(
                row.start_node,
                row.end_node,
                link_id=row.link_id,
                length=row.length_m,
                safety_score=row.safety_score,
                nature_score=row.nature_score,
                slope_score=row.slope_score,
                running_score=row.running_score,
                landmark_score=row.landmark_score,
                child_score=row.child_score,
            )
        return G

    @staticmethod
    def load_graph() -> nx.Graph:
        """
        walk_nodes와 walk_edges 전체를 읽어 NetworkX 그래프로 반환합니다.
        최대 연결 컴포넌트와 dead-end 제거를 적용합니다.
        """
        with get_postgresql_db() as db:
            node_rows = db.execute(GraphRepository._node_stmt()).fetchall()
            edge_rows = db.execute(GraphRepository._edge_stmt()).fetchall()

        G = GraphRepository._build_graph(node_rows, edge_rows)
        print(f"그래프 로드 완료: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        G = remove_dead_ends(G)
        print(f"최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")
        return G

    @staticmethod
    def load_graph_near(lat: float, lon: float, radius_m: float = 3000) -> nx.Graph:
        """
        특정 위치 반경 내 노드·엣지만 읽어 NetworkX 그래프로 반환합니다.

        Args:
            lat      : 중심 위도.
            lon      : 중심 경도.
            radius_m : 탐색 반경(미터). 기본값 3,000.
        """
        center = cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography())

        with get_postgresql_db() as db:
            node_rows = db.execute(
                GraphRepository._node_stmt().where(
                    func.ST_DWithin(cast(WalkNode.geom, Geography()), center, radius_m)
                )
            ).fetchall()

            edge_rows = db.execute(
                GraphRepository._edge_stmt().where(
                    func.ST_DWithin(cast(WalkEdge.geom, Geography()), center, radius_m)
                )
            ).fetchall()

        G = GraphRepository._build_graph(node_rows, edge_rows)
        print(f"반경 {radius_m}m 그래프 로드: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")

        largest_cc = max(nx.connected_components(G), key=len)
        G = G.subgraph(largest_cc).copy()
        print(f"최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")
        return G


# 하위 호환을 위한 모듈 수준 함수
load_graph = GraphRepository.load_graph
load_graph_near = GraphRepository.load_graph_near
