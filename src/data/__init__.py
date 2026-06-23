"""
Data layer public exports.

Collector imports are intentionally lazy so lightweight modules such as
src.data.intake can run without importing DB/GIS dependencies first.
"""

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
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    if name not in _EXPORTS:
        raise AttributeError(f"module 'src.data' has no attribute {name!r}")

    module = import_module(_EXPORTS[name])
    value = getattr(module, name)
    globals()[name] = value
    return value
