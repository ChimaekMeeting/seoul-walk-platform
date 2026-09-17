import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import networkx as nx

from src.config.settings import settings
from src.interfaces.schema.walk_schema import Coordinate, WalkMode, WalkRouteResponse

logger = logging.getLogger(__name__)

WALKING_SPEED_KMH = 4.8
SCORE_FIELDS = [
    "safety_score",
    "nature_score",
    "slope_score",
    "running_score",
    "landmark_score",
    "child_score",
    "convenience_score",
    "accessibility_score",
]


def append_route_metrics(record: dict[str, Any]) -> None:
    """Append one route metrics record as JSONL."""
    path = Path(settings.ROUTE_METRICS_LOG_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(_json_safe(record), ensure_ascii=False, sort_keys=True))
        fp.write("\n")


def build_route_metrics_record(
    *,
    request_id: str,
    requested_at: datetime,
    elapsed_ms: float,
    access_token_present: bool,
    user_id: Optional[int],
    origin: Coordinate,
    destination: Optional[Coordinate],
    target_km: Optional[float],
    mode: WalkMode,
    profile: Optional[Any],
    custom_weights: Optional[Any],
    engine: Optional[Any],
    result: WalkRouteResponse,
) -> dict[str, Any]:
    """Build the route request/result metrics payload persisted to JSONL."""
    algorithm = type(engine).__name__ if engine is not None else None
    effective_weights = _model_dump_or_none(getattr(engine, "weights", None)) or _model_dump_or_none(custom_weights)
    path_nodes = list(getattr(engine, "last_path_nodes", []) or [])
    engine_graph = getattr(engine, "G", None)

    actual_km = float(result.total_km or 0.0)
    target_error_km = abs(actual_km - target_km) if target_km is not None else None
    target_achievement_rate = (actual_km / target_km * 100.0) if target_km else None

    total_custom_score = _path_custom_score(engine, engine_graph, path_nodes)
    quality_density = (
        total_custom_score / max(actual_km * 1000.0, 1.0)
        if total_custom_score is not None and actual_km > 0
        else None
    )
    shortest_km = _shortest_distance_km(engine, engine_graph, path_nodes, mode)
    detour_ratio = (actual_km / shortest_km) if shortest_km and actual_km > 0 else None
    average_scores = _average_edge_scores(engine_graph, path_nodes)

    status = result.status.value
    return {
        "request_id": request_id,
        "requested_at": requested_at.astimezone(timezone.utc).isoformat(),
        "user_id": user_id,
        "session_id": None,
        "auth_token_present": access_token_present,
        "route_mode": mode.value,
        "algorithm": algorithm,
        "origin": {"lat": origin.lat, "lon": origin.lon},
        "destination": (
            {"lat": destination.lat, "lon": destination.lon}
            if destination is not None
            else None
        ),
        "target_km": target_km,
        "profile": _enum_value(profile),
        "weights": effective_weights,
        "status": status,
        "success": status == "success",
        "failure_reason": None if status == "success" else status,
        "result": {
            "actual_total_km": actual_km,
            "estimated_minutes": (actual_km / WALKING_SPEED_KMH * 60.0) if actual_km > 0 else 0.0,
            "coordinate_count": len(result.coordinates),
            "node_count": len(path_nodes),
            "total_custom_score": total_custom_score,
            "quality_density": quality_density,
            "target_error_km": target_error_km,
            "target_achievement_rate": target_achievement_rate,
            "shortest_total_km": shortest_km,
            "detour_ratio": detour_ratio,
            "average_scores": average_scores,
            "algorithm_runtime_ms": elapsed_ms,
            "coordinates": result.coordinates,
        },
    }


def _model_dump_or_none(value: Optional[Any]) -> Optional[dict[str, Any]]:
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dumped if isinstance(dumped, dict) else None
    if isinstance(value, dict):
        return value
    return None


def _enum_value(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None
    return getattr(value, "value", str(value))


def _path_custom_score(engine: Any, graph: Any, path_nodes: list[int]) -> Optional[float]:
    if len(path_nodes) < 2:
        return None
    if hasattr(engine, "path_cost"):
        try:
            return float(engine.path_cost(path_nodes))
        except Exception:
            logger.debug("route metrics path_cost failed", exc_info=True)
    if not isinstance(graph, nx.Graph):
        return None
    total = 0.0
    for u, v in zip(path_nodes, path_nodes[1:]):
        data = graph.get_edge_data(u, v) or {}
        total += float(data.get("custom_score", 1.0) or 1.0)
    return total


def _shortest_distance_km(
    engine: Any,
    graph: Any,
    path_nodes: list[int],
    mode: WalkMode,
) -> Optional[float]:
    if mode == WalkMode.CIRCULAR_RANDOM or len(path_nodes) < 2 or not isinstance(graph, nx.Graph):
        return None

    try:
        if hasattr(engine, "inp") and hasattr(engine.inp, "start_lat"):
            start = engine.utils.find_nearest_node(engine.inp.start_lat, engine.inp.start_lon)
            end = engine.utils.find_nearest_node(engine.inp.end_lat, engine.inp.end_lon)
        else:
            start, end = path_nodes[0], path_nodes[-1]
        if start is None or end is None:
            return None
        shortest_m = nx.shortest_path_length(graph, start, end, weight="length")
        return float(shortest_m) / 1000.0
    except Exception:
        logger.debug("route metrics shortest distance failed", exc_info=True)
        return None


def _average_edge_scores(graph: Any, path_nodes: list[int]) -> dict[str, Optional[float]]:
    scores: dict[str, list[float]] = {field: [] for field in SCORE_FIELDS}
    if len(path_nodes) < 2 or not isinstance(graph, nx.Graph):
        return {field.replace("_score", ""): None for field in SCORE_FIELDS}

    for u, v in zip(path_nodes, path_nodes[1:]):
        data = graph.get_edge_data(u, v) or {}
        for field in SCORE_FIELDS:
            value = data.get(field)
            if value is None:
                continue
            try:
                scores[field].append(float(value))
            except (TypeError, ValueError):
                continue

    return {
        field.replace("_score", ""): (sum(values) / len(values) if values else None)
        for field, values in scores.items()
    }


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
