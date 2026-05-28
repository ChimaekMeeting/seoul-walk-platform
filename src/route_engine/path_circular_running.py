"""
런닝/다이어트 순환 경로 추천 모듈.

DB에서 river·park·bike_track 코스를 조회한 뒤,
사용자 출발점 기준 편향 랜덤 워크(path_circular_random)로 순환 경로를 생성합니다.

호출 전 필수 조건
-----------------
- G의 각 엣지에 ``custom_score`` 속성이 세팅되어 있어야 합니다.
  (_apply_running_weights() 를 먼저 호출하세요.)

외부 의존성
-----------
- src.service.route.path_circular_random.random_walk_route
- src.repository.route.course_repository.get_courses_near
"""

import networkx as nx

from src.route_engine.path_circular_random import random_walk_route
from src.route_engine.path_utils import find_nearest_node
from src.repository.layer.course_repository import CourseRepository

RUNNING_COURSE_TYPES = ["river", "park", "bike_track"]


def circular_running_route(
    G: nx.Graph,
    start_lat: float,
    start_lon: float,
    target_m: float,
    radius_m: float,
    session,
) -> dict:
    """
    런닝/다이어트 순환 경로를 생성합니다.

    반경 내 river·park·bike_track 코스를 DB에서 조회하여 ``matched_courses``로 반환하고,
    사용자 출발점(start_lat, start_lon)에서 편향 랜덤 워크로 순환 경로를 생성합니다.

    .. note::
        ``G``의 각 엣지에 ``custom_score``가 없으면 경로 품질이 보장되지 않습니다.
        호출 전에 ``_apply_running_weights(G)``를 먼저 실행하세요.

        ``session`` 파라미터는 인터페이스 일관성을 위해 존재하며,
        실제 DB 연결은 ``get_courses_near()`` 내부에서 자체 관리합니다.

    Args:
        G         (nx.Graph)  : ``custom_score``가 세팅된 NetworkX 그래프.
        start_lat (float)     : 사용자 출발 위도.
        start_lon (float)     : 사용자 출발 경도.
        target_m  (float)     : 목표 거리 (미터).
        radius_m  (float)     : DB 코스 검색 반경 (미터).
        session               : 미사용. 서명 통일 목적으로만 존재.

    Returns:
        dict: 아래 키를 포함하는 딕셔너리.

        - ``mode``              (str)        : ``"circular_running"``
        - ``coordinates``       (list)       : ``[[lat, lon], ...]`` 형태의 경로 좌표 목록.
        - ``total_distance_km`` (float)      : 생성된 경로의 총 거리 (km).
        - ``matched_courses``   (list[dict]) : 반경 내 조회된 코스 목록.
          코스가 없으면 빈 리스트. 각 항목은 ``get_courses_near()`` 반환 형식과 동일.
    """
    courses = CourseRepository.get_courses_near(
        lat=start_lat,
        lon=start_lon,
        radius_m=radius_m,
        is_circular=True,
        course_types=RUNNING_COURSE_TYPES,
    )

    # 매칭 코스 없으면 사용자 위치에서 폴백
    if not courses:
        start_node = find_nearest_node(G, start_lat, start_lon)
        result = random_walk_route(G, start_node, target_m / 1000, weight="custom_score")
        result["mode"] = "circular_running"
        result["matched_courses"] = []
        return result

    start_node = find_nearest_node(G, start_lat, start_lon)

    result = random_walk_route(G, start_node, target_m / 1000, weight="custom_score")
    result["mode"] = "circular_running"
    result["matched_courses"] = courses
    return result
