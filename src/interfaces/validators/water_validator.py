from sqlalchemy import text

_DSNAP_M = 100.0

_SQL_ON_WATER = text("""
    SELECT EXISTS(
        SELECT 1 FROM seoul_water_polygons
        WHERE ST_Within(
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
            geom
        )
    )
""")

_SQL_NEAREST_NODE = text("""
    SELECT
        ST_Y(geom) AS snapped_lat,
        ST_X(geom) AS snapped_lon
    FROM walk_nodes
    WHERE ST_DWithin(
        geom::geography,
        ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
        :dsnap
    )
    ORDER BY geom::geography <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography
    LIMIT 1
""")


def snap_coordinate_from_water(
    lat: float,
    lon: float,
    db,
    dsnap: float = _DSNAP_M,
) -> tuple[float, float]:
    """
    VAL-COORD-005: 수계(한강/하천) 위 좌표 검증 및 보정
    - 수계 밖이면 원래 좌표를 그대로 반환
    - 수계 위 + dsnap(기본 100m) 이내 보행 노드 존재 → 해당 노드로 Snap
    - 수계 위 + dsnap 이내 노드 없음 → ValueError
    """
    on_water: bool = db.execute(_SQL_ON_WATER, {"lat": lat, "lon": lon}).scalar()

    if not on_water:
        return lat, lon

    row = db.execute(_SQL_NEAREST_NODE, {"lat": lat, "lon": lon, "dsnap": dsnap}).fetchone()

    if row is None:
        raise ValueError("선택하신 위치는 보행이 불가능한 길입니다.")

    return row.snapped_lat, row.snapped_lon
