from sqlalchemy import delete, insert, text

from src.database.postgresql import engine, get_postgresql_db
from src.entity.layer.route_poi import RoutePoi


class RoutePoiRepository:
    @staticmethod
    def find_near_route(
        coordinates: list[list[float]],
        max_distance_m: float = 50.0,
        limit: int = 20,
    ) -> list[dict]:
        """경로 선에서 지정 거리 안에 있는 도보망 연결 POI를 가까운 순서로 반환합니다."""
        if len(coordinates) < 2:
            return []

        points = ", ".join(f"{float(lon)} {float(lat)}" for lat, lon in coordinates)
        route_wkt = f"LINESTRING({points})"
        statement = text(
            """
            WITH route AS (
                SELECT ST_GeomFromText(:route_wkt, 4326) AS geom
            )
            SELECT
                poi.category,
                poi.name,
                poi.address,
                ST_Y(poi.geom) AS lat,
                ST_X(poi.geom) AS lon,
                ST_Distance(
                    poi.geom::geography,
                    route.geom::geography
                ) AS distance_to_route_m
            FROM route_pois AS poi
            CROSS JOIN route
            WHERE poi.is_route_connected = true
              AND ST_DWithin(
                    poi.geom::geography,
                    route.geom::geography,
                    :max_distance_m
                  )
            ORDER BY distance_to_route_m, poi.id
            LIMIT :limit
            """
        )
        with get_postgresql_db() as db:
            rows = db.execute(
                statement,
                {
                    "route_wkt": route_wkt,
                    "max_distance_m": max_distance_m,
                    "limit": limit,
                },
            ).mappings().all()
        return [
            {
                "category": row["category"],
                "name": row["name"],
                "address": row["address"],
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "distance_to_route_m": round(
                    float(row["distance_to_route_m"]),
                    1,
                ),
            }
            for row in rows
        ]

    @staticmethod
    def get_connected_counts_by_edge() -> dict[int, dict[str, int]]:
        """도보망에 연결된 POI 수를 Edge와 서비스 용도별로 반환합니다."""
        statement = text(
            """
            SELECT
                nearest_edge_id,
                COUNT(*) FILTER (
                    WHERE category = 'toilet'
                ) AS toilet_count,
                COUNT(*) FILTER (
                    WHERE category = 'transit'
                ) AS transit_count,
                COUNT(*) FILTER (
                    WHERE category = 'accessibility'
                ) AS accessibility_poi_count
            FROM route_pois
            WHERE is_route_connected = true
              AND nearest_edge_id IS NOT NULL
            GROUP BY nearest_edge_id
            """
        )
        with get_postgresql_db() as db:
            rows = db.execute(statement).fetchall()
        return {
            int(row.nearest_edge_id): {
                "toilet_count": int(row.toilet_count),
                "transit_count": int(row.transit_count),
                "accessibility_poi_count": int(
                    row.accessibility_poi_count
                ),
            }
            for row in rows
        }

    @staticmethod
    def replace_source(source_name: str, records: list[dict]) -> None:
        """한 원본의 POI를 최신 스냅샷으로 교체합니다."""
        if not records:
            raise ValueError(f"{source_name} POI 원본이 비어 있습니다.")

        with get_postgresql_db() as db:
            db.execute(
                delete(RoutePoi).where(RoutePoi.source_name == source_name)
            )
            db.execute(insert(RoutePoi), records)
            db.commit()

        RoutePoiRepository.create_spatial_index()

    @staticmethod
    def create_spatial_index() -> None:
        """
        POI 연결 쿼리의 geography 표현과 같은 GiST 인덱스를 준비합니다.

        geometry 인덱스만 있으면 ``geom::geography`` ST_DWithin 조인에서
        WalkEdge·WalkNode 전체를 반복 비교할 수 있으므로 세 표현을 모두
        명시적으로 인덱싱합니다.
        """
        with engine.begin() as connection:
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_route_pois_geom "
                "ON route_pois USING GIST(geom)"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_route_pois_geog "
                "ON route_pois USING GIST ((geom::geography))"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_walk_edges_geog "
                "ON walk_edges USING GIST ((geom::geography))"
            ))
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_walk_nodes_geog "
                "ON walk_nodes USING GIST ((geom::geography))"
            ))

    @staticmethod
    def connect_source_to_network(
        source_name: str,
        max_distance_m: float = 50.0,
    ) -> int:
        """
        지정 원본의 Point를 50m 안의 최근접 WalkEdge·WalkNode에 연결합니다.

        한도를 넘는 Point는 지도 표시 전용으로 남습니다.
        """
        reset = text(
            """
            UPDATE route_pois
            SET nearest_node_id = NULL,
                nearest_edge_id = NULL,
                distance_m = NULL,
                is_route_connected = false
            WHERE source_name = :source_name
            """
        )
        edge_update = text(
            """
            WITH nearest_edges AS (
                SELECT DISTINCT ON (poi.id)
                    poi.id AS poi_id,
                    edge.link_id,
                    ST_Distance(
                        poi.geom::geography,
                        edge.geom::geography
                    ) AS distance_m
                FROM route_pois AS poi
                JOIN walk_edges AS edge
                  ON ST_DWithin(
                        poi.geom::geography,
                        edge.geom::geography,
                        :max_distance_m
                     )
                WHERE poi.source_name = :source_name
                ORDER BY poi.id, distance_m, edge.link_id
            )
            UPDATE route_pois AS poi
            SET nearest_edge_id = nearest.link_id,
                distance_m = nearest.distance_m,
                is_route_connected = true
            FROM nearest_edges AS nearest
            WHERE poi.id = nearest.poi_id
            """
        )
        node_update = text(
            """
            WITH nearest_nodes AS (
                SELECT DISTINCT ON (poi.id)
                    poi.id AS poi_id,
                    node.node_id,
                    ST_Distance(
                        poi.geom::geography,
                        node.geom::geography
                    ) AS distance_m
                FROM route_pois AS poi
                JOIN walk_nodes AS node
                  ON ST_DWithin(
                        poi.geom::geography,
                        node.geom::geography,
                        :max_distance_m
                     )
                WHERE poi.source_name = :source_name
                ORDER BY poi.id, distance_m, node.node_id
            )
            UPDATE route_pois AS poi
            SET nearest_node_id = nearest.node_id
            FROM nearest_nodes AS nearest
            WHERE poi.id = nearest.poi_id
            """
        )
        params = {
            "source_name": source_name,
            "max_distance_m": max_distance_m,
        }
        with engine.begin() as connection:
            connection.execute(reset, params)
            result = connection.execute(edge_update, params)
            connection.execute(node_update, params)
        return result.rowcount
