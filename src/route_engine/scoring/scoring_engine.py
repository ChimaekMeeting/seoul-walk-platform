import math
import networkx as nx


def calculate_custom_score(graph: nx.Graph, profile: dict) -> nx.Graph:
    """
    graph 각 edge의 feature와 profile 가중치를 곱해 custom_score를 계산하여 부여합니다.

    공식:
        slope_penalty        = (2.0 - slope_score) ^ slope_w
        effective_type_bonus = 1.0 + type_bonus  (river/park/bike_track/trail)
                             | 1.0               (일반 엣지)
        length_bonus         = 1.0 + log1p(length / 50.0)

        [일반/평지]
        custom_score = (length * slope_penalty) / (safety^a * nature^b + ε)

        [런닝]
        custom_score = (length * slope_factor) / (safety * nature * type_bonus * length_bonus + ε)

    주의:
        Dijkstra는 음수 비용에 취약하므로 custom_score는 최소 1.0 이상으로 보정한다.
        blocked_tags가 포함된 edge는 inf로 설정하여 탐색에서 제외한다.

    금지:
        경로 탐색(다익스트라 등) 알고리즘 실행 금지

    Args:
        graph   : feature들이 바인딩된 NetworkX 그래프
        profile : {
            "mode"         : "general" | "running"   (기본값: "general")
            "weights"      : {"safety": float, "nature": float, "slope": float}
            "blocked_tags" : [str, ...]
            "type_bonus"   : float  (런닝 모드 전용, 기본값 1.0)
        }

    Returns:
        custom_score 속성이 추가된 graph
    """
    mode = profile.get("mode", "general")
    weights = profile.get("weights", {})
    blocked_tags = profile.get("blocked_tags", [])
    type_bonus = profile.get("type_bonus", 1.0)

    safety_w = weights.get("safety", 1.0)
    nature_w = weights.get("nature", 1.0)
    slope_w = weights.get("slope", 1.0)

    PREFERRED_PATH_TYPES = {"river", "park", "bike_track", "trail"}

    for u, v, data in graph.edges(data=True):
        # blocked_tags가 포함된 edge는 탐색에서 제외
        if any(tag in data.get("tags", []) for tag in blocked_tags):
            graph[u][v]["custom_score"] = float("inf")
            continue

        length = data.get("length", 1.0) or 1.0
        safety = data.get("safety_score", 0.5)
        nature = data.get("nature_score", 0.5)
        slope = data.get("slope_score", 0.5)
        path_type = (data.get("path_type") or "").lower()

        if mode == "running":
            # 런닝 전용 공식 (route_engine/engines/running_route_service.py 에서 분리)
            effective_type_bonus = (
                1.0 + type_bonus if path_type in PREFERRED_PATH_TYPES else 1.0
            )
            slope_factor = 1.0 + slope * slope_w
            length_bonus = 1.0 + math.log1p(length / 50.0)
            calculated = (length * slope_factor) / (
                (safety + 1e-6) * (nature + 1e-6) * effective_type_bonus * length_bonus
            )
        else:
            # 일반/평지 공식 (route_engine/engines/route_flat.py 에서 분리)
            slope_penalty = (2.0 - slope) ** slope_w
            calculated = (length * slope_penalty) / (
                (safety + 1e-6) ** safety_w * (nature + 1e-6) ** nature_w
            )

        # Dijkstra 음수 비용 방지
        graph[u][v]["custom_score"] = max(1.0, calculated)

    return graph
