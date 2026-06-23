from typing import Optional, List, Literal, Union
from pydantic import BaseModel, field_validator, model_validator
from enum import Enum

from src.interfaces.validators.coord_validator import (
    validate_coordinate_not_empty,
    validate_coordinate_parseable,
    validate_coordinates,
    validate_seoul_bounding_box,
)
from src.interfaces.validators.dist_validator import (
    validate_target_km_max,
    validate_target_km_positive,
    validate_target_km_vs_dest_proximity,
    validate_target_km_vs_straight_dist,
)
from src.interfaces.validators.mode_validator import (
    sanitize_circular_destination,
    validate_oneway_requires_destination,
)


class Coordinate(BaseModel):
    lat: float
    lon: float

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def check_coordinate_not_empty(cls, value: object) -> object:
        return validate_coordinate_not_empty(value)

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def check_coordinate_parseable(cls, value: object) -> object:
        return validate_coordinate_parseable(value)

    @model_validator(mode="after")
    def check_coordinates(self) -> "Coordinate":
        validate_coordinates(self.lat, self.lon)
        validate_seoul_bounding_box(self.lat, self.lon)
        return self


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

    @field_validator("target_km", mode="before")
    @classmethod
    def check_target_km_positive(cls, value: object) -> object:
        return validate_target_km_positive(value)

    @field_validator("target_km", mode="before")
    @classmethod
    def check_target_km_max(cls, value: object) -> object:
        return validate_target_km_max(value)

    @model_validator(mode="after")
    def sanitize_destination_for_circular(self) -> "WalkRouteRequest":
        self.destination = sanitize_circular_destination(self.mode.value, self.destination)
        return self

    @model_validator(mode="after")
    def check_oneway_requires_destination(self) -> "WalkRouteRequest":
        validate_oneway_requires_destination(self.mode.value, self.destination)
        return self

    @model_validator(mode="after")
    def check_oneway_requires_target_km(self) -> "WalkRouteRequest":
        """VAL-DIST-005: 편도 모드에서 target_km 누락 차단"""
        if isinstance(self.mode, OnewayMode) and self.target_km is None:
            raise ValueError("편도 모드에서는 목표 산책 거리(target_km) 입력이 필수입니다.")
        return self

    @model_validator(mode="after")
    def check_target_km_vs_straight_dist(self) -> "WalkRouteRequest":
        if (
            isinstance(self.mode, OnewayMode)
            and self.destination is not None
            and self.target_km is not None
        ):
            validate_target_km_vs_straight_dist(
                self.target_km,
                self.origin.lat, self.origin.lon,
                self.destination.lat, self.destination.lon,
            )
        return self

    @model_validator(mode="after")
    def check_target_km_vs_dest_proximity(self) -> "WalkRouteRequest":
        if (
            isinstance(self.mode, OnewayMode)
            and self.destination is not None
            and self.target_km is not None
        ):
            validate_target_km_vs_dest_proximity(
                self.target_km,
                self.origin.lat, self.origin.lon,
                self.destination.lat, self.destination.lon,
            )
        return self


class WalkRouteResponse(BaseModel):
    status:          Literal["SUCCESS", "FAILED"]
    mode:            Union[CircularMode, OnewayMode]
    coordinates:     list[list[float]]
    total_km:        float = 0.0
    fallback_reason: Optional[FallbackReason] = None