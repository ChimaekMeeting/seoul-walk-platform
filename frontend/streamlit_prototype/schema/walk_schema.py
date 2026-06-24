"""
frontend/streamlit_prototype/schema/walk_schema.py

FE는 BE 스키마를 그대로 재사용한다 (단일 소스 — BE와 항상 일치).
별도 정의를 두지 않고 src의 정의를 re-export 한다.
"""
from src.interfaces.schema.walk_schema import (
    Coordinate,
    WalkMode,
    WalkRouteStatus,
    WalkRouteRequest,
    WalkRouteResponse,
)

__all__ = [
    "Coordinate",
    "WalkMode",
    "WalkRouteStatus",
    "WalkRouteRequest",
    "WalkRouteResponse",
]
