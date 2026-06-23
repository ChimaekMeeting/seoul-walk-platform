def validate_coordinate_not_empty(value: object) -> object:
    """
    VAL-COORD-002: 위도/경도 null·빈 값 검증 (field_validator mode='before')
    """
    if value is None or (isinstance(value, str) and value.strip() == ""):
        raise ValueError("필수 위치 정보(위도 또는 경도)가 누락되었거나 빈 값입니다.")
    return value


def validate_coordinate_parseable(value: object) -> object:
    """
    VAL-COORD-003: 좌표값이 숫자로 파싱 불가능한 문자열 검증 (field_validator mode='before')
    """
    if isinstance(value, str):
        try:
            float(value)
        except ValueError:
            raise ValueError("좌표 데이터 형식이 올바르지 않습니다.")
    return value


_SEOUL_BBOX = {
    "lat_min": 37.41, "lat_max": 37.70,
    "lon_min": 126.73, "lon_max": 127.27,
}


def is_within_seoul_bbox(lat: float, lon: float) -> bool:
    """
    VAL-COORD-004 1차: 서울 최소 외접 사각형 안에 있는지 빠르게 판단합니다.
    """
    b = _SEOUL_BBOX
    return b["lat_min"] <= lat <= b["lat_max"] and b["lon_min"] <= lon <= b["lon_max"]


def validate_seoul_bounding_box(lat: float, lon: float) -> None:
    """
    VAL-COORD-004 1차: 서울 바운딩 박스 초과 시 예외를 발생시킵니다.
    """
    if not is_within_seoul_bbox(lat, lon):
        raise ValueError("출발/도착지가 서울 서비스 구역 외곽에 위치하고 있습니다.")


def validate_seoul_polygon_contains(lat: float, lon: float, db) -> None:
    """
    VAL-COORD-004 2차: seoul_administrative_boundary 폴리곤 포함 여부를 PostGIS로 정밀 검증합니다.
    1차를 통과한 경우에만 호출합니다.
    """
    from sqlalchemy import text

    result = db.execute(
        text("""
            SELECT EXISTS(
                SELECT 1
                FROM seoul_administrative_boundary
                WHERE ST_Within(
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326),
                    geom
                )
            )
        """),
        {"lat": lat, "lon": lon},
    ).scalar()

    if not result:
        raise ValueError("출발/도착지가 서울 서비스 구역 외곽에 위치하고 있습니다.")


def validate_coordinates(lat: float, lon: float) -> None:
    """
    VAL-COORD-001: 위도/경도 유효 범위 검증
    lat: -90.0 ~ 90.0
    lon: -180.0 ~ 180.0
    """
    if lat < -90.0 or lat > 90.0 or lon < -180.0 or lon > 180.0:
        raise ValueError("위치 정보(위경도)가 지구상 유효 범위를 초과했습니다.")
