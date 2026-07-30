from typing import Optional
from pydantic import BaseModel, Field

class CircularRouteInput(BaseModel):
    start_lat: float
    start_lon: float
    target_km: Optional[float] = None


class OnewayRouteInput(BaseModel):
    start_lat: float
    start_lon: float
    end_lat:   float
    end_lon:   float
    target_km: Optional[float] = None


class Weights(BaseModel):
    safety:   float = Field(0.5, ge=0.0, le=1.0, description="안전 점수 가중치 (safety_score)")
    nature:   float = Field(0.0, ge=0.0, le=1.0, description="자연 점수 가중치 (nature_score). 기본 0.0(중립)")
    slope:    float = Field(0.5, ge=0.0, le=1.0, description="경사 회피 가중치 (slope_score)")
    running:  float = Field(0.0, ge=0.0, le=1.0, description="러닝 코스 선호 가중치 (running_score)")
    landmark: float = Field(0.0, ge=0.0, le=1.0, description="랜드마크 선호 가중치 (landmark_score)")
    child:    float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="어린이보호구역 차량 주의 회피 가중치",
    )
    convenience: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="상권·화장실·대중교통 편의 선호 가중치",
    )
    accessibility: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="리프트·엘리베이터 인접 경로 선호 가중치",
    )
