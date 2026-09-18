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


# walk_schema.py에 이미 있는 좌표·모드 정의를 가져다 쓰지 않고, 이 파일 안에서 최소한으로
# 다시 정의한다 — route_schema.py는 route_engine이 쓰는 저수준 스키마라 interfaces 계층인
# walk_schema.py에 의존하지 않게 두기 위해서다.
# oneway_preferred는 oneway_shortest와 같은 A* 엔진을 쓰되 안전·편안 가중 비용을
# 적용하는 구간이다(#445). 둘을 나눠 두는 이유는 "사용자가 명시적으로 고른 최단"과
# "지정하지 않아 서비스가 채운 연결"을 구분하기 위해서다 — 명시적으로 고른 최단
# 구간을 저장된 선호 때문에 가중 연결로 바꾸면 안 된다. 어느 쪽을 채울지는
# RouteService가 leg를 자동 패딩하기 **전에** 정한다.
WaypointLegMode = Literal["oneway_shortest", "oneway_random", "oneway_preferred"]


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
    # 기본값은 survey_service.py의 BASE_WEIGHTS/BASE_COMFORT와 같은 값을 SSOT로 공유한다.
    # safety는 온보딩 미완료·미선택 시에도 0.5(무난히 중요)에서 시작하고, comfort는
    # 0.0(명시적으로 고르기 전엔 무편향)에서 시작해 두 축의 baseline이 서로 다르다.
    safety:  float = Field(0.5, ge=0.0, le=1.0, description="안전 점수 가중치")
    comfort: float = Field(0.0, ge=0.0, le=1.0, description="편안 점수 가중치")


class GpsArtPoint(BaseModel):
    """정규화된 도형 좌표 하나(로컬 좌표계, 단위 없음). 실제 위경도 변환은 route_engine에서 수행한다."""
    x: float
    y: float


class GpsArtRouteInput(BaseModel):
    shape_points: list[GpsArtPoint]  # 도형을 이루는 좌표, 순서대로 연결된다
    origin_lat:   float              # 도형을 배치할 중심 위경도
    origin_lon:   float
    target_km:    float              # 목표 총 이동 거리(km). route_engine이 이 값에 맞춰 도형 스케일을 계산한다

    @model_validator(mode="after")
    def check_min_points(self) -> "GpsArtRouteInput":
        if len(self.shape_points) < 2:
            raise ValueError("shape_points는 최소 2개 이상이어야 합니다")
        return self

    @model_validator(mode="after")
    def close_shape(self) -> "GpsArtRouteInput":
        """마지막 점이 첫 점과 다르면 첫 점을 다시 붙여 도형을 닫는다."""
        if self.shape_points[0] != self.shape_points[-1]:
            self.shape_points = [*self.shape_points, self.shape_points[0]]
        return self

    @model_validator(mode="after")
    def check_target_km_positive(self) -> "GpsArtRouteInput":
        if self.target_km <= 0:
            raise ValueError("target_km은 0보다 커야 합니다")
        return self
