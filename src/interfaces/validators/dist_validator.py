from math import asin, cos, radians, sin, sqrt


def validate_target_km_positive(value: object) -> object:
    """
    VAL-DIST-001: target_km > 0 검증 (field_validator mode='before')
    None이면 통과 (Optional 필드이므로 Pydantic에 위임)
    """
    if value is None or not isinstance(value, (int, float)):
        return value
    if value <= 0.0:
        raise ValueError("목표 산책 거리는 0 이하로 설정할 수 없습니다.")
    return value


def validate_target_km_max(value: object) -> object:
    """
    VAL-DIST-002: target_km <= 10.0 검증 (field_validator mode='before')
    None이면 통과 (Optional 필드이므로 Pydantic에 위임)
    """
    if value is None or not isinstance(value, (int, float)):
        return value
    if value > 10.0:
        raise ValueError("목표 산책 거리가 너무 깁니다. 최대 10km 이하로 설정해주세요.")
    return value


def _haversine_km(origin_lat: float, origin_lon: float, dest_lat: float, dest_lon: float) -> float:
    lon1, lat1, lon2, lat2 = map(radians, [origin_lon, origin_lat, dest_lon, dest_lat])
    dlon, dlat = lon2 - lon1, lat2 - lat1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * 6371 * asin(sqrt(a))


_PROXIMITY_RATIO = 0.15  # straight_dist / target_km 최솟값


def validate_target_km_vs_dest_proximity(
    target_km: float,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> None:
    """
    VAL-DIST-004: 편도 모드에서 목적지가 target_km 대비 지나치게 가까울 때 차단
    조건: straight_dist / target_km < 0.15
    """
    straight_dist = _haversine_km(origin_lat, origin_lon, dest_lat, dest_lon)
    if straight_dist / target_km < _PROXIMITY_RATIO:
        max_km = round(straight_dist / _PROXIMITY_RATIO, 1)
        raise ValueError(
            f"목적지가 목표 거리에 비해 너무 가깝습니다. "
            f"경로가 과도하게 우회될 수 있어 경로를 제공할 수 없습니다. "
            f"목표 거리를 {max_km}km 이하로 설정하세요."
        )


def validate_target_km_vs_straight_dist(
    target_km: float,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> None:
    """
    VAL-DIST-003: 편도 모드에서 target_km < 출발-도착 직선거리(하버사인) 차단
    """
    straight_dist = _haversine_km(origin_lat, origin_lon, dest_lat, dest_lon)
    if target_km < straight_dist:
        raise ValueError("목표 산책 거리가 출발지와 도착지 사이의 직선거리보다 짧습니다.")
