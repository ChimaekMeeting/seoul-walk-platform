import streamlit as st
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

    def render_params(self) -> RouteParams:
        d = self.default_params()
        return RouteParams(
            mode_key       = self.mode_key,
            distance_km    = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, d.distance_km, 0.5, key="distance_km"),
            child_friendly = d.child_friendly,
            safety_w       = d.safety_w,
            nature_w       = d.nature_w,
        )

