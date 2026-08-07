import math

import networkx as nx
import numpy as np


COMFORT_TAG_PENALTIES = {
    "tunnel": 1.20,
    "overpass": 1.12,
    "subway_network": 1.08,
    "building_inside": 1.08,
}

# 후보 경로를 다양화할 때 쓰는 벡터 score의 차원. custom_score의 profile 가중치와는
# 무관하게, 대표 후보(가중 스칼라 기준 1등)와 다른 두 후보를 고를 때만 쓴다.
VECTOR_SCORE_DIMENSIONS = ("safety", "nature", "slope", "convenience", "accessibility")

_FEATURE_CACHE_KEY = "_scoring_feature_cache"


def _clamp_score_arr(arr: np.ndarray) -> np.ndarray:
    return np.clip(np.nan_to_num(arr, nan=0.0), 0.0, 1.0)


def _bounded_count_score_arr(count_arr: np.ndarray, saturation_count: int) -> np.ndarray:
    safe = np.maximum(0, count_arr.astype(np.int64))
    return np.minimum(1.0, np.log1p(safe) / math.log1p(saturation_count))


def _build_feature_cache(graph: nx.Graph) -> dict:
    edges = list(graph.edges(data=True))
    n = len(edges)

    edge_keys = [(u, v) for u, v, _ in edges]
    length_raw = np.empty(n, dtype=np.float64)
    safety_raw = np.empty(n, dtype=np.float64)
    nature_raw = np.empty(n, dtype=np.float64)
    park_raw = np.empty(n, dtype=np.float64)
    slope_raw = np.empty(n, dtype=np.float64)
    landmark_raw = np.empty(n, dtype=np.float64)
    running_raw = np.empty(n, dtype=np.float64)
    convenience_raw = np.empty(n, dtype=np.float64)
    toilet_count = np.empty(n, dtype=np.int64)
    transit_count = np.empty(n, dtype=np.int64)
    accessibility_count = np.empty(n, dtype=np.int64)
    is_vehicle_caution = np.empty(n, dtype=bool)
    comfort_penalty = np.ones(n, dtype=np.float64)
    tags_list: list[list[str]] = []

    for i, (_, _, data) in enumerate(edges):
        length_raw[i] = max(1.0, float(data.get("length", 1.0) or 1.0))
        safety_raw[i] = data.get("safety_score") or 0.0
        nature_raw[i] = data.get("nature_score") or 0.0
        park_raw[i] = data.get("park_overlap_ratio") or 0.0
        slope_raw[i] = data.get("slope_score") or 0.0
        landmark_raw[i] = data.get("landmark_score") or 0.0
        running_raw[i] = data.get("running_score") or 0.0
        convenience_raw[i] = data.get("convenience_score") or 0.0
        toilet_count[i] = int(data.get("toilet_count", 0) or 0)
        transit_count[i] = int(data.get("transit_count", 0) or 0)
        accessibility_count[i] = int(data.get("accessibility_poi_count", 0) or 0)
        is_vehicle_caution[i] = bool(data.get("is_vehicle_caution", False))

        tags = data.get("tags", []) or []
        tags_list.append(tags)
        for tag, penalty in COMFORT_TAG_PENALTIES.items():
            if tag in tags:
                comfort_penalty[i] = max(comfort_penalty[i], penalty)

    convenience_poi = _bounded_count_score_arr(toilet_count + transit_count, saturation_count=3)

    return {
        "edge_keys": edge_keys,
        "length": length_raw,
        "safety": _clamp_score_arr(safety_raw),
        "nature": np.maximum(_clamp_score_arr(nature_raw), _clamp_score_arr(park_raw)),
        "slope": _clamp_score_arr(slope_raw),
        "landmark": _clamp_score_arr(landmark_raw),
        "running": _clamp_score_arr(running_raw),
        "convenience": np.maximum(_clamp_score_arr(convenience_raw), convenience_poi),
        "accessibility": _bounded_count_score_arr(accessibility_count, saturation_count=2),
        "is_vehicle_caution": is_vehicle_caution,
        "comfort_penalty": comfort_penalty,
        "tags_list": tags_list,
    }


def precompute_scoring_features(graph: nx.Graph) -> None:
    graph.graph[_FEATURE_CACHE_KEY] = _build_feature_cache(graph)


def _get_feature_cache(graph: nx.Graph) -> dict:
    cache = graph.graph.get(_FEATURE_CACHE_KEY)
    if cache is None or len(cache["edge_keys"]) != graph.number_of_edges():
        cache = _build_feature_cache(graph)
        graph.graph[_FEATURE_CACHE_KEY] = cache
    return cache


def _compute_scores_array(graph: nx.Graph, profile: dict) -> tuple[list[tuple], np.ndarray, dict]:
    """
    calculate_custom_score / compute_custom_score_lookup가 공유하는 계산 코어.
    그래프에 아무것도 쓰지 않고 (edge_keys, custom_score 배열, feature cache)만 반환한다.
    """
    mode         = profile.get("mode", "general")
    weights      = profile.get("weights", {})
    blocked_tags = profile.get("blocked_tags", [])

    def _w(key: str, default: float = 0.0) -> float:
        if isinstance(weights, dict):
            return weights.get(key, default)
        return getattr(weights, key, default)

    safety_w        = _w("safety",   1.0)
    nature_w        = _w("nature",   1.0)
    slope_w         = _w("slope",    1.0)
    landmark_w      = _w("landmark", 0.0)
    child_w         = _w("child",    0.0)
    running_w       = _w("running",  0.0)
    convenience_w   = _w("convenience", 0.0)
    accessibility_w = _w("accessibility", 0.0)

    cache = _get_feature_cache(graph)

    bonus = (
        (1.0 + cache["safety"] * safety_w)
        * (1.0 + cache["nature"] * nature_w)
        * (1.0 + cache["landmark"] * landmark_w)
        * (1.0 + cache["convenience"] * convenience_w)
        * (1.0 + cache["accessibility"] * accessibility_w)
    )
    slope_penalty = 1.0 + (1.0 - cache["slope"]) * slope_w
    caution_penalty = np.where(cache["is_vehicle_caution"], 1.0 + child_w, 1.0)
    comfort_penalty = cache["comfort_penalty"]

    if mode == "running":
        bonus = bonus * (1.0 + cache["running"] * running_w)
        bonus = bonus * (1.0 + np.log1p(cache["length"] / 50.0))

    calculated = (
        cache["length"] * slope_penalty * caution_penalty * comfort_penalty
    ) / np.maximum(bonus, 1e-6)
    custom_score = np.maximum(1.0, calculated)

    if blocked_tags:
        blocked_mask = np.array(
            [any(tag in tags for tag in blocked_tags) for tags in cache["tags_list"]],
            dtype=bool,
        )
        custom_score = np.where(blocked_mask, np.inf, custom_score)

    return cache["edge_keys"], custom_score, cache


def calculate_custom_score(graph: nx.Graph, profile: dict) -> nx.Graph:
    """
    기존 동작 유지 — beam/grasp/alns/rcsp/plateau 등 그래프 mutation에 의존하는
    엔진들을 위해 그대로 남겨둔다. A*/Dijkstra/Bi-A*는 이제 이 함수 대신
    compute_custom_score_lookup을 쓴다.
    """
    edge_keys, custom_score, _ = _compute_scores_array(graph, profile)
    graph.graph["_last_custom_score_array"] = custom_score
    for (u, v), score in zip(edge_keys, custom_score.tolist()):
        graph[u][v]["custom_score"] = score
    return graph


def compute_custom_score_lookup(graph: nx.Graph, profile: dict) -> dict:
    """
    calculate_custom_score와 동일한 계산이지만 그래프에 쓰지 않는다.
    G.copy() 없이(원본을 전혀 건드리지 않고) 매 요청 다른 가중치로 반복 계산할 때 사용.

    반환:
        {"weight": callable(u, v, data) -> float,  # nx.astar_path/shortest_path의 weight= 인자로 그대로 사용
         "lookup": {(u, v): score, ...},           # 경로 비용 직접 합산용
         "min_ratio": float}                       # A* admissibility 하한 비율
    """
    edge_keys, custom_score, cache = _compute_scores_array(graph, profile)

    lookup: dict[tuple, float] = {}
    for (u, v), score in zip(edge_keys, custom_score.tolist()):
        lookup[(u, v)] = score
        lookup[(v, u)] = score  # 무방향 그래프이므로 양방향 조회 등록

    min_ratio = float(np.min(custom_score / np.maximum(cache["length"], 1e-6)))

    def _weight(u, v, d, _lookup=lookup):
        return _lookup.get((u, v), 1.0)

    return {"weight": _weight, "lookup": lookup, "min_ratio": min_ratio}


def compute_score_vector(graph: nx.Graph) -> dict[tuple, dict[str, float]]:
    """
    완성된 후보 경로들을 다양화하기 위한 edge별 벡터 비용을 계산한다.
    calculate_custom_score/compute_custom_score_lookup과 달리 profile 가중치를 쓰지 않는다
    — 대표 후보(후보 1)는 기존 가중 스칼라(custom_score)로 뽑고, 나머지 후보(2·3)는
    가중치와 무관한 "순수 품질 차이"로 다양화하기 위해 별도로 존재한다.

    각 차원 값은 length * (1 - feature)다. feature(0~1, 1이 가장 좋음)가 1이면 0,
    0이면 length 전체가 그 차원의 비용으로 잡힌다 — custom_score처럼 경로를 따라
    그대로 합산할 수 있다(path_utils.path_score_vector 참고).

    반환: {(u, v): {"safety": cost, "nature": cost, ...}, (v, u): {...}, ...}
    (무방향 그래프이므로 양방향 조회 등록, compute_custom_score_lookup과 동일 패턴)
    """
    cache = _get_feature_cache(graph)

    vectors: dict[tuple, dict[str, float]] = {}
    for i, (u, v) in enumerate(cache["edge_keys"]):
        length = float(cache["length"][i])
        edge_vector = {
            dim: length * (1.0 - float(cache[dim][i]))
            for dim in VECTOR_SCORE_DIMENSIONS
        }
        vectors[(u, v)] = edge_vector
        vectors[(v, u)] = edge_vector

    return vectors
