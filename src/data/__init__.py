"""Data layer collector exports."""

from importlib import import_module
from typing import Any


_EXPORTS = {
    "BaseNetworkCollector": "src.data.collectors.base_collector",
    "NatureCollector": "src.data.collectors.nature_collector",
    "SafetyCollector": "src.data.collectors.safety_collector",
    "LandmarkCollector": "src.data.collectors.landmark_collector",
    "RunningCourseCollector": "src.data.collectors.running_collector",
    "SlopeCalculator": "src.data.collectors.slope_collector",
    "ChildCollector": "src.data.collectors.child_collector",
    "CommercialCollector": "src.data.collectors.commercial_collector",
    "EdgeFeatureCollector": "src.data.collectors.edge_feature_collector",
    "RoutePoiCollector": "src.data.collectors.route_poi_collector",
    "SeoulBoundaryCollector": "src.data.collectors.boundary_collector",
    "SeoulWaterCollector": "src.data.collectors.water_collector",
    "ParkPolygonCollector": "src.data.collectors.park_polygon_collector",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module 'src.data' has no attribute {name!r}")

    module = import_module(_EXPORTS[name])
    value = getattr(module, name)
    globals()[name] = value
    return value
