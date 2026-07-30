import networkx as nx
from typing import Any

from src.repository.network.graph_repository import GraphRepository


def load_route_graph(request: dict[str, Any]) -> nx.Graph:
    """
    추천 요청에 필요한 도로망 graph를 준비합니다.
    GraphRepository를 중간 레이어로 감싸 route_engine이 DB를 직접 의존하지 않도록 합니다.

    Args:
        request: {
            "lat"      : float  사용자 위치 위도
            "lon"      : float  사용자 위치 경도
            "radius_m" : float  탐색 반경 (미터, 기본값 3000)
        }

    Returns:
        nx.Graph: route_engine 표준 node/edge attribute를 가진 그래프
            node 속성: lon, lat, node_type, is_underground, is_overpass
            edge 속성: link_id, length, safety_score, nature_score, slope_score,
                       running_score, landmark_score, child_score,
                       park_overlap_ratio, convenience_score,
                       is_school_zone, is_vehicle_caution,
                       toilet_count, transit_count, accessibility_poi_count

    금지:
        custom_score 계산, profile 선택, route algorithm 호출 금지
        기존 src/service/route import 금지
    """
    lat = request["lat"]
    lon = request["lon"]
    radius_m = request.get("radius_m", 3000)

    return GraphRepository.load_graph_near(lat=lat, lon=lon, radius_m=radius_m)
