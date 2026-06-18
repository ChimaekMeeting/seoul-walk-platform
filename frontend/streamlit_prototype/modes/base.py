import streamlit as st
from abc import ABC
from dataclasses import dataclass
from typing import ClassVar


@dataclass
class RouteParams:
    mode_key:  str
    target_km: float


class BaseRouteMode(ABC):
    label:    ClassVar[str]
    mode_key: ClassVar[str]

    def default_params(self) -> RouteParams:
        return RouteParams(mode_key=self.mode_key, target_km=3.0)

    def render_params(self) -> RouteParams:
        return RouteParams(
            mode_key  = self.mode_key,
            target_km = st.sidebar.slider("목표 거리 (km)", 1.0, 10.0, 3.0, 0.5, key="target_km"),
        )
