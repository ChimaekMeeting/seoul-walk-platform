from math import asin, cos, isfinite, radians, sin, sqrt


def _coerce_finite_target_km(value: object) -> object:
    """숫자와 숫자 문자열을 유한한 float로 변환하고 boolean은 거절합니다."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("목표 산책 거리는 숫자로 입력해주세요.")
    try:
        number = float(value)
    except (TypeError, ValueError):
        # 숫자가 아닌 입력의 형식 오류는 뒤이은 Pydantic float 검증이 보고한다.
        return value
    if not isfinite(number):
        raise ValueError("목표 산책 거리는 유한한 숫자로 입력해주세요.")
    return number


def validate_target_km_positive(value: object) -> object:
    """
    VAL-DIST-001: target_km > 0 검증 (field_validator mode='before')
    None이면 통과 (Optional 필드이므로 Pydantic에 위임)
    """
    value = _coerce_finite_target_km(value)
    if value is None or not isinstance(value, float):
        return value
    if value <= 0.0:
        raise ValueError("목표 산책 거리는 0 이하로 설정할 수 없습니다.")
    return value


def validate_target_km_max(value: object) -> object:
    """
    VAL-DIST-002: target_km <= 10.0 검증 (field_validator mode='before')
    None이면 통과 (Optional 필드이므로 Pydantic에 위임)
    """
    value = _coerce_finite_target_km(value)
    if value is None or not isinstance(value, float):
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
