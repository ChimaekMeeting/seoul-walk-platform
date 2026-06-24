from typing import Optional, List, Union
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


class WalkRouteStatus(str, Enum):
    SUCCESS                = "success"
    INVALID_ORIGIN         = "invalid_origin"
    INVALID_DESTINATION    = "invalid_destination"
    NO_NEAREST_START_NODE  = "no_nearest_start_node"
    NO_NEAREST_END_NODE    = "no_nearest_end_node"
    NO_PATH                = "no_path"
    RETURN_PATH_NOT_FOUND  = "return_path_not_found"
    PARTIAL_ROUTE          = "partial_route"
    WEIGHT_RELAXED         = "weight_relaxed"
    RADIUS_EXPANDED        = "radius_expanded"
    UNKNOWN_ERROR          = "unknown_error"
    ACCESS_EXPIRED_TOKEN   = "access_expired_token"
    INVALID_TOKEN          = "invalid_token"


class WalkRouteRequest(BaseModel):
    origin:      Coordinate
    destination: Optional[Coordinate] = None
    target_km:   Optional[float] = None
    mode:        Union[CircularMode, OnewayMode]


class WalkRouteResponse(BaseModel):
    status:      WalkRouteStatus
    mode:        Union[CircularMode, OnewayMode]
    coordinates: list[list[float]]
    total_km:    float = 0.0
