from typing import Optional, List, Literal, Union
from pydantic import BaseModel
from enum import Enum


class Coordinate(BaseModel):
    lat: float
    lon: float


class CircularMode(str, Enum):
    RANDOM   = "circular_random"
    CHILD    = "circular_child"
    RUNNING  = "circular_running"
    LANDMARK = "circular_landmark"
    FLAT     = "circular_flat"


class OnewayMode(str, Enum):
    SHORTEST = "oneway_shortest"
    RANDOM   = "oneway_random"
    CHILD    = "oneway_child"
    RUNNING  = "oneway_running"
    LANDMARK = "oneway_landmark"
    FLAT     = "oneway_flat"


class FallbackReason(str, Enum):
    ACCESS_EXPIRED_TOKEN   = "access_expired_token"
    INVALID_TOKEN          = "invalid_token"
    INVALID_ORIGIN         = "INVALID_ORIGIN"
    INVALID_DESTINATION    = "INVALID_DESTINATION"
    NO_NEAREST_START_NODE  = "NO_NEAREST_START_NODE"
    NO_NEAREST_END_NODE    = "NO_NEAREST_END_NODE"
    NO_PATH                = "NO_PATH"
    RETURN_PATH_NOT_FOUND  = "RETURN_PATH_NOT_FOUND"
    PARTIAL_ROUTE          = "PARTIAL_ROUTE"
    WEIGHT_RELAXED         = "WEIGHT_RELAXED"
    RADIUS_EXPANDED        = "RADIUS_EXPANDED"
    UNKNOWN_ERROR          = "UNKNOWN_ERROR"


class WalkRouteRequest(BaseModel):
    origin:      Coordinate
    destination: Optional[Coordinate] = None
    target_km:   Optional[float] = None
    mode:        Union[CircularMode, OnewayMode]


class WalkRouteResponse(BaseModel):
    status:          Literal["SUCCESS", "FAILED"]
    mode:            Union[CircularMode, OnewayMode]
    coordinates:     list[list[float]]
    total_km:        float = 0.0
    fallback_reason: Optional[FallbackReason] = None