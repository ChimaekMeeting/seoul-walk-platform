from typing import Optional
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


class WalkMode(str, Enum):
    CIRCULAR_RANDOM = "circular_random"
    ONEWAY_SHORTEST = "oneway_shortest"
    ONEWAY_RANDOM = "oneway_random"


class WalkRouteStatus(str, Enum):
    SUCCESS = "success"
    INVALID_ORIGIN = "invalid_origin"
    INVALID_DESTINATION = "invalid_destination"
    NO_NEAREST_START_NODE = "no_nearest_start_node"
    NO_NEAREST_END_NODE = "no_nearest_end_node"
    NO_PATH = "no_path"
    RETURN_PATH_NOT_FOUND = "return_path_not_found"
    PARTIAL_ROUTE = "partial_route"
    WEIGHT_RELAXED = "weight_relaxed"
    RADIUS_EXPANDED = "radius_expanded"
    UNKNOWN_ERROR = "unknown_error"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    INVALID_TOKEN = "invalid_token"


class WalkRouteRequest(BaseModel):
    origin: Coordinate
    destination: Optional[Coordinate] = None
    target_km: Optional[float] = None
    mode: WalkMode

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
        """VAL-DIST-005: 편도 랜덤 모드에서 target_km 누락 차단"""
        if self.mode == WalkMode.ONEWAY_RANDOM and self.target_km is None:
            raise ValueError("편도 랜덤 모드에서는 목표 산책 거리(target_km) 입력이 필수입니다.")
        return self

    @model_validator(mode="after")
    def check_target_km_vs_straight_dist(self) -> "WalkRouteRequest":
        if (
            self.mode == WalkMode.ONEWAY_RANDOM
            and self.destination is not None
            and self.target_km is not None
        ):
            validate_target_km_vs_straight_dist(
                self.target_km,
                self.origin.lat,
                self.origin.lon,
                self.destination.lat,
                self.destination.lon,
            )
        return self

    @model_validator(mode="after")
    def check_target_km_vs_dest_proximity(self) -> "WalkRouteRequest":
        if (
            self.mode == WalkMode.ONEWAY_RANDOM
            and self.destination is not None
            and self.target_km is not None
        ):
            validate_target_km_vs_dest_proximity(
                self.target_km,
                self.origin.lat,
                self.origin.lon,
                self.destination.lat,
                self.destination.lon,
            )
        return self


class WalkRouteResponse(BaseModel):
    status: WalkRouteStatus
    mode: WalkMode
    coordinates: list[list[float]]
    total_km: float = 0.0
