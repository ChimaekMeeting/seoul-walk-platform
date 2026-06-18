from enum import Enum
from typing import Literal, Optional, Union
from pydantic import BaseModel, Field

class CircularRouteInput(BaseModel):
    start_lat: float
    start_lon: float
    target_km: float | None = None


class OnewayRouteInput(BaseModel):
    start_lat: float
    start_lon: float
    end_lat:   float
    end_lon:   float
    target_km: float | None = None


class Weights(BaseModel):
    safety:   float = Field(0.5, ge=0.0, le=1.0, description="안전 점수 가중치 (safety_score)")
    nature:   float = Field(0.5, ge=0.0, le=1.0, description="자연 점수 가중치 (nature_score)")
    slope:    float = Field(0.5, ge=0.0, le=1.0, description="경사 회피 가중치 (slope_score)")
    running:  float = Field(0.0, ge=0.0, le=1.0, description="러닝 코스 선호 가중치 (running_score)")
    landmark: float = Field(0.0, ge=0.0, le=1.0, description="랜드마크 선호 가중치 (landmark_score)")
    child:    float = Field(0.0, ge=0.0, le=1.0, description="어린이 보호구역 가중치 (child_score)")
