import networkx as nx

from src.route_engine.features import build_running_weights
from src.route_engine.schema import EngineWeights


def apply_weights(G: nx.Graph, weights: EngineWeights) -> nx.Graph:
    """
    EngineWeights에 선언된 feature만 사용해 custom_score를 엣지에 적용합니다.
    """
    for u, v, data in G.edges(data=True):
        score = 1.0
        if weights.safety is not None:
            score /= (data.get("safety_score", 0.5) + 1e-6)
        if weights.nature is not None:
            score /= (data.get("nature_score", 0.5) + 1e-6)
        if weights.slope is not None:
            score *= 1.0 + data.get("slope_score", 0.5) * weights.slope
        G[u][v]["custom_score"] = score
    return G


def apply_running_weights(G: nx.Graph, weights: EngineWeights | None = None) -> nx.Graph:
    """
    러닝 가중치를 그래프 엣지의 custom_score에 적용합니다.
    """
    w = build_running_weights(weights)
    slope_weight = w.slope or 0.5
    PREFERRED_PATH_TYPES = {"river", "park", "bike_track", "trail"}
    for u, v, data in G.edges(data=True):
        safety    = data.get("safety_score", 0.5)
        nature    = data.get("nature_score", 0.5)
        slope     = data.get("slope_score", 0.5)
        path_type = data.get("path_type", "") or ""

        type_bonus   = 2.0 if path_type.lower() in PREFERRED_PATH_TYPES else 1.0
        slope_factor = 1.0 + slope * slope_weight
        G[u][v]["custom_score"] = slope_factor / (
            (safety + 1e-6) * (nature + 1e-6) * type_bonus
        )
    return G
