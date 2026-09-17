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
# oneway_preferred는 oneway_shortest와 같은 A* 엔진을 쓰되 안전·편안 가중 비용을
# 적용하는 구간이다(#445). 둘을 나눠 두는 이유는 "사용자가 명시적으로 고른 최단"과
# "지정하지 않아 서비스가 채운 연결"을 구분하기 위해서다 — 명시적으로 고른 최단
# 구간을 저장된 선호 때문에 가중 연결로 바꾸면 안 된다. 어느 쪽을 채울지는
# RouteService가 leg를 자동 패딩하기 **전에** 정한다.
WaypointLegMode = Literal["oneway_shortest", "oneway_random", "oneway_preferred"]


class WaypointCoordinate(BaseModel):
    lat: float
    lon: float


class SafetyComfortPreference(BaseModel):
    """가중 연결에 전달할 안전·편안 선호(#445).

    챗봇은 프로필/설문 기본값과 이번 대화의 요구를 섞은 최종 Weights에서 두 축을
    전달한다. 기본값 0.5도 유효하며, 발화에 없는 축을 임의로 끄지 않는다.
    직접 호출자가 축을 생략하면 해당 축은 None(계수 0)이다.
    """

    safety:  Optional[float] = Field(None, ge=0.0, le=1.0)
    comfort: Optional[float] = Field(None, ge=0.0, le=1.0)

    @property
    def is_active(self) -> bool:
        return self.safety is not None or self.comfort is not None

    def as_coefficients(self) -> tuple[float, float]:
        """비용 계수 변환에 넘길 (safety, comfort). 지정하지 않은 축은 0이다 —
        기본값 0.5가 아니라 0이어야 그 축에 페널티가 걸리지 않는다."""
        return (self.safety or 0.0, self.comfort or 0.0)


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
