"""
graph_repository_v2.py
────────────────────────────────────────────────────────
기존 graph_repository.py를 건드리지 않고, slope_score + nature_score를
모두 로드하는 새 버전.

변경점 (기존 대비):
  - load_graph()     → load_graph_v2()      : nature_score 컬럼 추가
  - load_graph_near() → load_graph_near_v2() : nature_score 컬럼 추가
  (기존에 slope_score는 있었으나 nature_score가 누락되어 있었음)

사용법:
  # app.py 또는 route 진입점에서 아래처럼 교체만 하면 됨
  from src.repository.graph_repository_v2 import load_graph_v2 as load_graph
  from src.repository.graph_repository_v2 import load_graph_near_v2 as load_graph_near
"""

import networkx as nx
from sqlalchemy import text
from src.database.postgresql import get_postgresql_db
from src.service.route.path_utils import remove_dead_ends


def load_graph_v2() -> nx.Graph:
    """
    walk_nodes + walk_edges를 PostGIS에서 읽어 NetworkX 그래프로 반환.
    기존 load_graph()에서 nature_score 컬럼 누락을 보완한 버전.

    Returns:
        G: Graph
            - node 속성: node_type, is_underground, is_overpass, x(lng), y(lat)
            - edge 속성: link_id, length, road_type, path_type,
                         safety_score, nature_score, slope_score  ← 3개 모두
    """
    G = nx.Graph()

    with get_postgresql_db() as db:
        # ── 노드 로드 (기존과 동일) ──────────────────
        node_rows = db.execute(text("""
            SELECT
                node_id,
                node_type,
                is_underground,
                is_overpass,
                ST_X(geom) AS lng,
                ST_Y(geom) AS lat
            FROM walk_nodes
        """)).fetchall()

        for row in node_rows:
            G.add_node(
                row.node_id,
                x=row.lng,
                y=row.lat,
                node_type=row.node_type,
                is_underground=row.is_underground,
                is_overpass=row.is_overpass,
            )

        # ── 엣지 로드 (nature_score 추가) ───────────
        edge_rows = db.execute(text("""
            SELECT
                link_id,
                start_node,
                end_node,
                length_m,
                road_type,
                path_type,
                safety_score,
                nature_score,
                slope_score
            FROM walk_edges
        """)).fetchall()

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

    print(
        f"[v2] 그래프 로드 완료: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개"
    )

    largest_cc = max(nx.connected_components(G), key=len)
    G = G.subgraph(largest_cc).copy()
    G = remove_dead_ends(G)
    print(
        f"[v2] 최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개"
    )

    return G


def load_graph_near_v2(lat: float, lng: float, radius_m: float = 3000) -> nx.Graph:
    """
    특정 위치 반경 내 노드/엣지만 로드 (전체 로드보다 빠름).
    기존 load_graph_near()에서 nature_score 컬럼 누락을 보완한 버전.

    Args:
        lat, lng : 중심 위경도
        radius_m : 반경 (미터)
    """
    G = nx.Graph()

    with get_postgresql_db() as db:
        node_rows = db.execute(
            text("""
            SELECT
                node_id,
                node_type,
                is_underground,
                is_overpass,
                ST_X(geom) AS lng,
                ST_Y(geom) AS lat
            FROM walk_nodes
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius
            )
        """),
            {"lat": lat, "lng": lng, "radius": radius_m},
        ).fetchall()

        for row in node_rows:
            G.add_node(
                row.node_id,
                x=row.lng,
                y=row.lat,
                node_type=row.node_type,
                is_underground=row.is_underground,
                is_overpass=row.is_overpass,
            )

        edge_rows = db.execute(
            text("""
            SELECT
                link_id, start_node, end_node,
                length_m, road_type, path_type,
                safety_score, nature_score, slope_score
            FROM walk_edges
            WHERE ST_DWithin(
                geom::geography,
                ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
                :radius
            )
        """),
            {"lat": lat, "lng": lng, "radius": radius_m},
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

    print(
        f"[v2] 반경 {radius_m}m 그래프 로드: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개"
    )

    largest_cc = max(nx.connected_components(G), key=len)
    G = G.subgraph(largest_cc).copy()
    print(
        f"[v2] 최대 연결 컴포넌트: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개"
    )

    return G
