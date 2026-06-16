from abc import ABC
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class RouteParams:
    mode_key:       str
    distance_km:    float
    child_friendly: bool
    safety_w:       float
    nature_w:       float


class BaseRouteMode(ABC):
    label:    ClassVar[str]
    mode_key: ClassVar[str]

    def default_params(self) -> RouteParams:
        return RouteParams(
            mode_key       = self.mode_key,
            distance_km    = 3.0,
            child_friendly = False,
            safety_w       = 1.0,
            nature_w       = 1.0,
        )
