from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ManeuverType(str, Enum):
    START = "start"
    STRAIGHT = "straight"
    SLIGHT_LEFT = "slight_left"
    SLIGHT_RIGHT = "slight_right"
    LEFT = "left"
    RIGHT = "right"
    U_TURN = "u_turn"
    ARRIVE = "arrive"


class RouteManeuver(BaseModel):
    sequence: int = Field(ge=0)
    type: ManeuverType
    instruction: str = Field(min_length=1)
    location: list[float] = Field(min_length=2, max_length=2)
    node_id: Optional[int] = None
    distance_from_start_m: float = Field(ge=0.0)
    distance_to_maneuver_m: float = Field(ge=0.0)
    bearing_before_deg: Optional[float] = Field(default=None, ge=0.0, lt=360.0)
    bearing_after_deg: Optional[float] = Field(default=None, ge=0.0, lt=360.0)
    turn_angle_deg: Optional[float] = Field(default=None, ge=0.0, le=180.0)
