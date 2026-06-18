import math

import networkx as nx


def calculate_custom_score(graph: nx.Graph, profile: dict) -> nx.Graph:
    """
    graph 각 edge의 feature와 profile 가중치를 곱해 custom_score를 계산하여 부여합니다.

    공식:
        [일반] custom_score = (length × slope_penalty) / (safety^a × nature^b × bonus + ε)
            slope_penalty = (2.0 - slope_score) ^ slope_w
            bonus         = (1 + landmark × landmark_w) × (1 + child × child_w)   -- 해당 가중치 > 0 시만 적용

        [런닝] custom_score = (length × slope_factor) / (safety × nature × running_bonus × length_bonus + ε)
            slope_factor  = 1.0 + slope_score × slope_w
            running_bonus = 1.0 + running_score × running_w
            length_bonus  = 1.0 + log1p(length / 50.0)

    주의:
        Dijkstra는 음수 비용에 취약하므로 custom_score는 최소 1.0으로 보정합니다.
        blocked_tags가 포함된 edge는 inf로 설정하여 탐색에서 제외합니다.

    Args:
        graph   : feature들이 바인딩된 NetworkX 그래프
        profile : {
            "mode"         : "general" | "running"  (기본값: "general")
            "weights"      : Weights 객체 또는 dict
            "blocked_tags" : [str, ...]
        }

    Returns:
        custom_score 속성이 추가된 graph
    """
    mode         = profile.get("mode", "general")
    weights      = profile.get("weights", {})
    blocked_tags = profile.get("blocked_tags", [])

    # Weights Pydantic 객체와 dict 모두 수용
    def _w(key: str, default: float = 0.0) -> float:
        if isinstance(weights, dict):
            return weights.get(key, default)
        return getattr(weights, key, default)

    safety_w   = _w("safety",   1.0)
    nature_w   = _w("nature",   1.0)
    slope_w    = _w("slope",    1.0)
    landmark_w = _w("landmark", 0.0)
    child_w    = _w("child",    0.0)
    running_w  = _w("running",  0.0)

    for u, v, data in graph.edges(data=True):
        if blocked_tags and any(tag in data.get("tags", []) for tag in blocked_tags):
            graph[u][v]["custom_score"] = float("inf")
            continue

        def _feature(key: str, default: float) -> float:
            # Some graph edges have nullable feature columns; use neutral defaults
            # so incomplete DB rows do not crash route generation.
            value = data.get(key, default)
            return default if value is None else float(value)

        length = data.get("length", 1.0) or 1.0
        safety = _feature("safety_score", 0.5)
        nature = _feature("nature_score", 0.5)
        slope  = _feature("slope_score",  0.5)

        if mode == "running":
            running       = _feature("running_score", 0.0)
            running_bonus = 1.0 + running * running_w
            slope_factor  = 1.0 + slope * slope_w
            length_bonus  = 1.0 + math.log1p(length / 50.0)
            calculated    = (length * slope_factor) / (
                (safety + 1e-6) * (nature + 1e-6) * running_bonus * length_bonus
            )
        else:
            slope_penalty = (2.0 - slope) ** slope_w
            denominator   = (safety + 1e-6) ** safety_w * (nature + 1e-6) ** nature_w
            if landmark_w > 0:
                denominator *= 1.0 + _feature("landmark_score", 0.0) * landmark_w
            if child_w > 0:
                denominator *= 1.0 + _feature("child_score", 0.0) * child_w
            calculated    = (length * slope_penalty) / denominator

        graph[u][v]["custom_score"] = max(1.0, calculated)

    return graph
