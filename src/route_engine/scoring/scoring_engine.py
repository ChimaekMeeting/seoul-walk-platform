import math

import networkx as nx


COMFORT_TAG_PENALTIES = {
    "tunnel": 1.20,
    "overpass": 1.12,
    "subway_network": 1.08,
    "building_inside": 1.08,
}


def _clamp_score(value, default: float = 0.0) -> float:
    if value is None:
        return default
    return max(0.0, min(1.0, float(value)))


def _bounded_count_score(count, saturation_count: int) -> float:
    """POI 개수를 0~1로 제한하며 saturation_count에서 상한에 도달시킵니다."""
    safe_count = max(0, int(count or 0))
    return min(
        1.0,
        math.log1p(safe_count) / math.log1p(saturation_count),
    )


def calculate_custom_score(graph: nx.Graph, profile: dict) -> nx.Graph:
    """
    graph 각 edge의 feature와 profile 가중치를 곱해 custom_score를 계산하여 부여합니다.

    양의 근거는 (1 + score × weight) 가점으로 사용하여 데이터가 없는
    지역(score=0)을 감점하지 않습니다. 경사·차량 주의·불쾌 구간은
    분자에 페널티로 반영합니다.

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
    convenience_w = _w("convenience", 0.0)
    accessibility_w = _w("accessibility", 0.0)

    for u, v, data in graph.edges(data=True):
        if blocked_tags and any(tag in data.get("tags", []) for tag in blocked_tags):
            graph[u][v]["custom_score"] = float("inf")
            continue

        length = max(1.0, float(data.get("length", 1.0) or 1.0))
        safety = _clamp_score(data.get("safety_score"))
        nature = max(
            _clamp_score(data.get("nature_score")),
            _clamp_score(data.get("park_overlap_ratio")),
        )
        slope = _clamp_score(data.get("slope_score"))
        landmark = _clamp_score(data.get("landmark_score"))
        running = _clamp_score(data.get("running_score"))

        convenience_poi = _bounded_count_score(
            int(data.get("toilet_count", 0) or 0)
            + int(data.get("transit_count", 0) or 0),
            saturation_count=3,
        )
        convenience = max(
            _clamp_score(data.get("convenience_score")),
            convenience_poi,
        )
        accessibility = _bounded_count_score(
            data.get("accessibility_poi_count", 0),
            saturation_count=2,
        )

        bonus = (
            (1.0 + safety * safety_w)
            * (1.0 + nature * nature_w)
            * (1.0 + landmark * landmark_w)
            * (1.0 + convenience * convenience_w)
            * (1.0 + accessibility * accessibility_w)
        )
        # slope_score는 경사도가 아니라 평탄도입니다.
        # 1.0은 평지, 0.0은 MAX_SLOPE_PCT 이상의 급경사를 뜻합니다.
        slope_penalty = 1.0 + (1.0 - slope) * slope_w
        caution_penalty = (
            1.0 + child_w
            if data.get("is_vehicle_caution", False)
            else 1.0
        )
        comfort_penalty = max(
            (
                penalty
                for tag, penalty in COMFORT_TAG_PENALTIES.items()
                if tag in data.get("tags", [])
            ),
            default=1.0,
        )

        if mode == "running":
            bonus *= 1.0 + running * running_w
            bonus *= 1.0 + math.log1p(length / 50.0)

        calculated = (
            length
            * slope_penalty
            * caution_penalty
            * comfort_penalty
        ) / max(bonus, 1e-6)

        graph[u][v]["custom_score"] = max(1.0, calculated)

    return graph
