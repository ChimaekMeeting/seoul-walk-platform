"""
src/repository/user/route_hash.py

경로 좌표로 route_hash(같은 경로 식별자)를 만든다(#524). RouteHistoryRepository.save가 저장할 때
계산해 route_histories.route_hash / route_hash_version에 넣는다.

규칙 v1: 좌표를 소수점 5자리로 반올림 -> 바로 앞 점과 같은 점 제거 -> compact JSON -> SHA-256.
방향과 시작점은 정규화하지 않는다(역방향이나 시작점만 다른 순환 경로는 다른 경로로 본다).
좌표 각 값을 그대로 반올림하므로 [lat, lon]과 [lon, lat] 어느 순서든 같은 좌표는 같은 hash가 된다.

정규화 규칙을 바꾸면 이전 hash와 비교할 수 없으므로 ROUTE_HASH_VERSION을 올린다("v2").
"""
import hashlib
import json
from typing import Iterable

ROUTE_HASH_VERSION = "v1"
COORDINATE_PRECISION = 5  # 소수점 5자리 ≈ 위도 1.1m


def normalize_route_coordinates(coordinates: Iterable[Iterable[float]]) -> list[list[float]]:
    """좌표를 반올림하고 연속으로 같은 점을 제거한다."""
    normalized: list[list[float]] = []
    for point in coordinates:
        rounded = [round(float(value), COORDINATE_PRECISION) for value in point]
        if normalized and rounded == normalized[-1]:
            continue
        normalized.append(rounded)
    return normalized


def create_route_hash(coordinates: Iterable[Iterable[float]]) -> tuple[str, str]:
    """(route_hash, route_hash_version)을 돌려준다. route_hash는 64자리 hex 문자열."""
    payload = json.dumps(normalize_route_coordinates(coordinates), separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), ROUTE_HASH_VERSION
