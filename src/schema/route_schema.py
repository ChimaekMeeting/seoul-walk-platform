from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

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


# route_schema.py -> walk_schema.py -> route_engine.profiles -> route_schema.py(Weights)로
# 이어지는 기존 순환 임포트가 있어, walk_schema의 Coordinate/WalkMode를 그대로 가져다 쓸 수 없다.
# 그래서 좌표·모드 값을 이 파일 안에서 최소한으로 다시 정의한다.
WaypointLegMode = Literal["oneway_shortest", "oneway_random"]


class WaypointCoordinate(BaseModel):
    lat: float
    lon: float


class WaypointRouteInput(BaseModel):
    start_lat: float
    start_lon: float
    end_lat:   float
    end_lon:   float
    waypoints: list[WaypointCoordinate] = Field(default_factory=list)
    leg_modes: list[WaypointLegMode]
    leg_target_km: list[Optional[float]]

    @model_validator(mode="after")
    def check_leg_counts(self) -> "WaypointRouteInput":
        expected_legs = len(self.waypoints) + 1
        if len(self.leg_modes) != expected_legs:
            raise ValueError(
                f"leg_modes 길이({len(self.leg_modes)})는 waypoints+1({expected_legs})과 같아야 합니다"
            )
        if len(self.leg_target_km) != expected_legs:
            raise ValueError(
                f"leg_target_km 길이({len(self.leg_target_km)})는 waypoints+1({expected_legs})과 같아야 합니다"
            )
        return self

    @model_validator(mode="after")
    def check_leg_target_km_for_random(self) -> "WaypointRouteInput":
        for mode, target_km in zip(self.leg_modes, self.leg_target_km):
            if mode == "oneway_random" and target_km is None:
                raise ValueError("oneway_random leg는 leg_target_km 값이 필요합니다")
        return self


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
