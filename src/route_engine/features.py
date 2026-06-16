from typing import Any

from src.route_engine.schema import EngineWeights


def build_flat_weights(weights: EngineWeights | None = None) -> EngineWeights:
    """
    평지 경로에 적합한 가중치를 생성합니다.
    """
    return EngineWeights(
        slope=weights.slope if weights is not None else 1.0,
    )


def build_random_weights(weights: EngineWeights | None = None) -> EngineWeights:
    """
    랜덤 워크 경로에 적합한 가중치를 생성합니다.
    """
    return EngineWeights(
        safety=weights.safety if weights is not None else 0.5,
        nature=weights.nature if weights is not None else 0.5,
    )


def build_landmark_weights(weights: EngineWeights | None = None) -> EngineWeights:
    """
    랜드마크 경유 경로에 적합한 가중치를 생성합니다.
    """
    return EngineWeights(
        safety=weights.safety if weights is not None else 0.5,
        nature=weights.nature if weights is not None else 0.5,
    )


def build_child_weights(weights: EngineWeights | None = None) -> EngineWeights:
    """
    어린이 동반 산책 경로에 적합한 가중치를 생성합니다.
    """
    return EngineWeights(
        safety=weights.safety if weights is not None else 1.0,
        nature=weights.nature if weights is not None else 1.0,
    )


def build_running_weights(weights: EngineWeights | None = None) -> EngineWeights:
    """
    러닝 경로에 적합한 가중치를 생성합니다.
    """
    return EngineWeights(
        safety=weights.safety if weights is not None else 0.5,
        nature=weights.nature if weights is not None else 0.5,
        slope=weights.slope if weights is not None else 0.5,
    )


