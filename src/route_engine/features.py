from typing import Any

from src.interfaces.schema.prewalk_schema import Weights


def build_child_weights(weights: Weights | None = None) -> Weights:
    """
    어린이 동반 산책 경로에 적합한 가중치를 생성합니다.
    """
    return Weights(
        safety=weights.safety if weights is not None else 1.0,
        nature=weights.nature if weights is not None else 1.0,
    )


def register_features(graph: Any, requested_features: list[str]) -> Any:
    pass


def base_feature_binder(graph: Any, context: dict[str, Any] | None = None) -> Any:
    pass


def bind_safety_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    pass


def bind_nature_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    pass


def bind_landmark_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    pass


def bind_slope_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    pass


def bind_live_poi_features(graph: Any, context: dict[str, Any] | None = None) -> Any:
    pass
