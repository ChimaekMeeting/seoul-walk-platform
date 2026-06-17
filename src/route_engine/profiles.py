from typing import Union
from pydantic import BaseModel

from src.schema.route_schema import CircularMode, OnewayMode, Weights

class ProfileConfig(BaseModel):
    weights:      Weights
    blocked_tags: list[str] = []

_DEFAULT  = ProfileConfig(weights=Weights(safety=0.5, nature=0.5, slope=0.5),                        blocked_tags=["underground"])
_FLAT     = ProfileConfig(weights=Weights(safety=0.5, nature=0.3, slope=1.0),                        blocked_tags=["underground"])
_CHILD    = ProfileConfig(weights=Weights(safety=1.0, nature=0.3, slope=1.0, child=1.0),             blocked_tags=["underground", "highway"])
_RUNNING  = ProfileConfig(weights=Weights(safety=0.5, nature=0.5, slope=0.7, running=1.0),           blocked_tags=["underground"])
_LANDMARK = ProfileConfig(weights=Weights(safety=0.5, nature=0.5, slope=0.3, landmark=1.0),          blocked_tags=["underground"])


# 모드별 가중치 프로필 매핑
PROFILES: dict[Union[CircularMode, OnewayMode], ProfileConfig] = {
    CircularMode.RANDOM:   _DEFAULT,
    CircularMode.FLAT:     _FLAT,
    CircularMode.CHILD:    _CHILD,
    CircularMode.RUNNING:  _RUNNING,
    CircularMode.LANDMARK: _LANDMARK,

    OnewayMode.SHORTEST:   _DEFAULT,
    OnewayMode.RANDOM:     _DEFAULT,
    OnewayMode.FLAT:       _FLAT,
    OnewayMode.CHILD:      _CHILD,
    OnewayMode.RUNNING:    _RUNNING,
    OnewayMode.LANDMARK:   _LANDMARK,
}


def get_profile(mode: Union[CircularMode, OnewayMode]) -> ProfileConfig:
    return PROFILES.get(mode, _DEFAULT)
