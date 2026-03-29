import networkx as nx
from sqlalchemy import text
from src.database.postgresql import get_postgresql_db


def load_graph() -> nx.DiGraph:
    """
    walk_nodes + walk_edges를 PostGIS에서 읽어 NetworkX 그래프로 반환

    Returns:
        G: DiGraph
            - node 속성: node_type, is_underground, is_overpass, x(lng), y(lat)
            - edge 속성: link_id, length, road_type, path_type, safety_score, slope_score
    """
    G = nx.DiGraph()

    with get_postgresql_db() as db:
        # ── 노드 로드 ──────────────────────────────
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
                x=row.lng,           # OSMnx 호환 (lng = x)
                y=row.lat,           # OSMnx 호환 (lat = y)
                node_type=row.node_type,
                is_underground=row.is_underground,
                is_overpass=row.is_overpass,
            )

        # ── 엣지 로드 ──────────────────────────────
        edge_rows = db.execute(text("""
            SELECT
                link_id,
                start_node,
                end_node,
                length_m,
                road_type,
                path_type,
                safety_score,
                slope_score
            FROM walk_edges
        """)).fetchall()

        for row in edge_rows:
            G.add_edge(
                row.start_node,
                row.end_node,
                link_id=row.link_id,
                length=row.length_m,     # route.py의 "length" 키와 맞춤
                road_type=row.road_type,
                path_type=row.path_type,
                safety_score=row.safety_score,
                slope_score=row.slope_score,
            )

    print(f"그래프 로드 완료: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")
    return G


def load_graph_near(lat: float, lng: float, radius_m: float = 3000) -> nx.DiGraph:
    """
    특정 위치 반경 내 노드/엣지만 로드 (전체 로드보다 빠름)

    Args:
        lat, lng: 중심 위경도
        radius_m: 반경 (미터)
    """
    G = nx.DiGraph()

    with get_postgresql_db() as db:
        node_rows = db.execute(text("""
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
        """), {"lat": lat, "lng": lng, "radius": radius_m}).fetchall()

        node_ids = set()
        for row in node_rows:
            G.add_node(
                row.node_id,
                x=row.lng,
                y=row.lat,
                node_type=row.node_type,
                is_underground=row.is_underground,
                is_overpass=row.is_overpass,
            )
            node_ids.add(row.node_id)

        edge_rows = db.execute(text("""
            SELECT
                link_id,
                start_node,
                end_node,
                length_m,
                road_type,
                path_type,
                safety_score,
                slope_score
            FROM walk_edges
            WHERE start_node = ANY(:node_ids)
              AND end_node   = ANY(:node_ids)
        """), {"node_ids": list(node_ids)}).fetchall()

        for row in edge_rows:
            G.add_edge(
                row.start_node,
                row.end_node,
                link_id=row.link_id,
                length=row.length_m,
                road_type=row.road_type,
                path_type=row.path_type,
                safety_score=row.safety_score,
                slope_score=row.slope_score,
            )

    print(f"반경 {radius_m}m 그래프 로드: 노드 {G.number_of_nodes()}개, 엣지 {G.number_of_edges()}개")
    return G