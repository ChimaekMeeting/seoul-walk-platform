from math import atan2, cos, degrees, radians, sin
from typing import Optional

from src.interfaces.schema.maneuver_schema import ManeuverType, RouteManeuver


def _bearing(start: list[float], end: list[float]) -> Optional[float]:
    if len(start) < 2 or len(end) < 2 or start == end:
        return None
    lat1, lat2 = radians(start[0]), radians(end[0])
    delta_lon = radians(end[1] - start[1])
    x = sin(delta_lon) * cos(lat2)
    y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(delta_lon)
    return (degrees(atan2(x, y)) + 360.0) % 360.0


def _distance_m(start: list[float], end: list[float]) -> float:
    radius_m = 6_371_000.0
    lat1, lat2 = radians(start[0]), radians(end[0])
    dlat = lat2 - lat1
    dlon = radians(end[1] - start[1])
    value = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * radius_m * atan2(value ** 0.5, (1 - value) ** 0.5)


def build_maneuvers(
    coordinates: list[list[float]],
    node_ids: Optional[list[int]] = None,
    turn_threshold_deg: float = 15.0,
) -> list[RouteManeuver]:
    if not coordinates:
        return []
    if node_ids is None:
        node_ids = []

    bearings = [_bearing(a, b) for a, b in zip(coordinates, coordinates[1:])]
    cumulative = [0.0]
    for start, end in zip(coordinates, coordinates[1:]):
        cumulative.append(cumulative[-1] + _distance_m(start, end))

    result: list[RouteManeuver] = []
    for index, point in enumerate(coordinates):
        before = bearings[index - 1] if index else None
        after = bearings[index] if index < len(bearings) else None
        angle = None
        if before is not None and after is not None:
            angle = min(abs(after - before), 360.0 - abs(after - before))

        if 0 < index < len(coordinates) - 1 and (angle is None or angle < turn_threshold_deg):
            continue

        if index == 0:
            kind, instruction = ManeuverType.START, "출발하세요."
        elif index == len(coordinates) - 1:
            kind, instruction = ManeuverType.ARRIVE, "도착했습니다."
        elif angle is not None and angle >= 135.0:
            kind, instruction = ManeuverType.U_TURN, "유턴하세요."
        else:
            delta = (after - before + 360.0) % 360.0
            kind = ManeuverType.RIGHT if delta < 180.0 else ManeuverType.LEFT
            instruction = "오른쪽으로 방향을 전환하세요." if kind == ManeuverType.RIGHT else "왼쪽으로 방향을 전환하세요."

        previous = cumulative[index - 1] if index else cumulative[index]
        result.append(RouteManeuver(
            sequence=len(result),
            type=kind,
            instruction=instruction,
            location=point,
            node_id=node_ids[index] if index < len(node_ids) else None,
            distance_from_start_m=cumulative[index],
            distance_to_maneuver_m=cumulative[index] - previous,
            bearing_before_deg=before,
            bearing_after_deg=after,
            turn_angle_deg=angle,
        ))
    return result
