from sqlalchemy import text

_DSNAP_M = 100.0

_SQL_WALKABLE_NODE_EXISTS = text("""
    SELECT EXISTS(
        SELECT 1
        FROM walk_nodes
        WHERE ST_DWithin(
            geom::geography,
            ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)::geography,
            :dsnap
        )
    )
""")


def validate_no_highway(
    lat: float,
    lon: float,
    db,
    dsnap: float = _DSNAP_M,
) -> None:
    """
    VAL-COORD-006 ②: Dsnap 이내 보행 가능 노드가 없으면 고속도로/전용도로로 판단하여 차단.
    walk_nodes는 전처리(①) 단계에서 이미 foot=no, highway=motorway 엣지를
    제외한 보행자 서브그래프만 포함한다고 가정합니다.
    수계 검증(VAL-COORD-005) 이후에 호출하세요.
    """
    exists: bool = db.execute(
        _SQL_WALKABLE_NODE_EXISTS,
        {"lat": lat, "lon": lon, "dsnap": dsnap},
    ).scalar()

    if not exists:
        raise ValueError("선택하신 위치는 고속도로 또는 자동차 전용도로 위 구역입니다.")
