from typing import Literal, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from enum import Enum

from src.interfaces.validators.coord_validator import (
    validate_coordinate_not_empty,
    validate_coordinate_parseable,
    validate_coordinates,
    validate_seoul_bounding_box,
)
from src.interfaces.validators.dist_validator import (
    validate_target_km_max,
    validate_target_km_positive,
    validate_target_km_vs_dest_proximity,
    validate_target_km_vs_straight_dist,
)
from src.interfaces.validators.mode_validator import (
    sanitize_circular_destination,
    validate_oneway_requires_destination,
)


class Coordinate(BaseModel):
    lat: float = Field(description="위도. 서울 영역의 유한한 좌표")
    lon: float = Field(description="경도. 서울 영역의 유한한 좌표")

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def check_coordinate_not_empty(cls, value: object) -> object:
        return validate_coordinate_not_empty(value)

    @field_validator("lat", "lon", mode="before")
    @classmethod
    def check_coordinate_parseable(cls, value: object) -> object:
        return validate_coordinate_parseable(value)

    @model_validator(mode="after")
    def check_coordinates(self) -> "Coordinate":
        validate_coordinates(self.lat, self.lon)
        validate_seoul_bounding_box(self.lat, self.lon)
        return self


class WalkMode(str, Enum):
    CIRCULAR_RANDOM = "circular_random"
    ONEWAY_SHORTEST = "oneway_shortest"
    ONEWAY_RANDOM = "oneway_random"
    WAYPOINT = "waypoint"
    GPS_ART = "gps_art"


class WalkRouteStatus(str, Enum):
    SUCCESS = "success"
    INVALID_ORIGIN = "invalid_origin"
    INVALID_DESTINATION = "invalid_destination"
    NO_NEAREST_START_NODE = "no_nearest_start_node"
    NO_NEAREST_END_NODE = "no_nearest_end_node"
    NO_PATH = "no_path"
    TIMEOUT = "timeout"
    RETURN_PATH_NOT_FOUND = "return_path_not_found"
    PARTIAL_ROUTE = "partial_route"
    WEIGHT_RELAXED = "weight_relaxed"
    RADIUS_EXPANDED = "radius_expanded"
    UNKNOWN_ERROR = "unknown_error"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    INVALID_TOKEN = "invalid_token"


class WalkRouteRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "origin": {"lat": 37.5665, "lon": 126.9780},
                "destination": None,
                "target_km": 3.0,
                "mode": "circular_random",
            }
        }
    )

    origin: Coordinate = Field(description="산책 출발 좌표")
    destination: Optional[Coordinate] = Field(
        default=None,
        description="편도 모드의 도착 좌표. 순환 모드에서는 무시됩니다.",
    )
    target_km: Optional[float] = Field(
        default=None,
        gt=0.0,
        le=10.0,
        allow_inf_nan=False,
        description="목표 산책 거리(km). 숫자 문자열도 허용하며 0 초과 10 이하의 유한한 값이어야 합니다.",
    )
    mode: WalkMode = Field(description="경로 생성 모드")
    # 편도 우회 재현성 제어. 생략하면 서비스 기본 seed를 사용한다.
    seed: Optional[int] = Field(default=None, ge=0, description="편도 우회 탐색 시드")

    @field_validator("target_km", mode="before")
    @classmethod
    def check_target_km_positive(cls, value: object) -> object:
        return validate_target_km_positive(value)

    @field_validator("target_km", mode="before")
    @classmethod
    def check_target_km_max(cls, value: object) -> object:
        return validate_target_km_max(value)

    @model_validator(mode="after")
    def sanitize_destination_for_circular(self) -> "WalkRouteRequest":
        self.destination = sanitize_circular_destination(self.mode.value, self.destination)
        return self

    @model_validator(mode="after")
    def check_oneway_requires_destination(self) -> "WalkRouteRequest":
        validate_oneway_requires_destination(self.mode.value, self.destination)
        return self

    @model_validator(mode="after")
    def check_oneway_requires_target_km(self) -> "WalkRouteRequest":
        """VAL-DIST-005: 편도 랜덤 모드에서 target_km 누락 차단"""
        if self.mode == WalkMode.ONEWAY_RANDOM and self.target_km is None:
            raise ValueError("편도 랜덤 모드에서는 목표 산책 거리(target_km) 입력이 필수입니다.")
        return self

    @model_validator(mode="after")
    def check_target_km_vs_straight_dist(self) -> "WalkRouteRequest":
        if (
            self.mode == WalkMode.ONEWAY_RANDOM
            and self.destination is not None
            and self.target_km is not None
        ):
            validate_target_km_vs_straight_dist(
                self.target_km,
                self.origin.lat,
                self.origin.lon,
                self.destination.lat,
                self.destination.lon,
            )
        return self

    @model_validator(mode="after")
    def check_target_km_vs_dest_proximity(self) -> "WalkRouteRequest":
        if (
            self.mode == WalkMode.ONEWAY_RANDOM
            and self.destination is not None
            and self.target_km is not None
        ):
            validate_target_km_vs_dest_proximity(
                self.target_km,
                self.origin.lat,
                self.origin.lon,
                self.destination.lat,
                self.destination.lon,
            )
        return self


class RoutePoiItem(BaseModel):
    category: str
    name: Optional[str] = None
    address: Optional[str] = None
    lat: float
    lon: float
    distance_to_route_m: float


PreferenceSkippedReason = Literal[
    "no_preference",
    "beam_leg_present",
    "scores_unavailable",
    "detour_cap_exceeded",
    "baseline_failed",
    "partial_route",
    "preferred_search_failed",
    "zero_weights",
]


class WalkRouteResponse(BaseModel):
    status: WalkRouteStatus
    mode: WalkMode
    coordinates: list[list[float]]
    total_km: float = 0.0
    # RouteHistory로 자동 저장된 경우에만 채워짐(즐겨찾기 등 PATCH /api/user/routes/{id}/favorite 호출에 사용).
    # 저장에 실패했거나 애초에 저장 대상이 아닌 응답(에러 상태 등)에서는 None.
    id: Optional[int] = None
    nearby_pois: list[RoutePoiItem] = Field(default_factory=list)
    # 요청한 새 가중 연결이 최종 전체 경로에 적용됐는지(#445).
    # 선호 구간 중 하나라도 거리 기준 대체로 바뀌면 False이며 사유를 함께 반환한다.
    preference_applied: bool = False
    # 반영하지 못한 사유. preference_applied=True면 보통 None이지만, baseline_failed는
    # 예외다 — 선호는 반영됐는데 우회 상한을 검증하지 못한 상태라 둘 다 채워진다.
    #   no_preference       호출자가 안전·편안 선호 신호를 전달하지 않음
    #   zero_weights        두 축의 계수가 모두 0이라 거리 기준으로 탐색
    #   beam_leg_present    oneway_random 구간이 섞여 이번 가중 연결 대상에서 제외
    #   scores_unavailable  그래프 점수 커버리지가 부족해 가중 모드가 꺼짐
    #   preferred_search_failed 선호 탐색 실패 후 거리 기준 경로로 대체
    #   partial_route       일부 구간 실패로 선호가 적용된 전체 경로를 반환하지 못함
    #   detour_cap_exceeded / baseline_failed는 보존한 실험 정책 전용이다.
    preference_skipped_reason: Optional[PreferenceSkippedReason] = None
    # 가중 탐색 진단: 실제 cost context 계수. API/벤치마크에서 거리 전용과
    # 안전·편안 조건을 구분할 수 있도록 노출한다.
    cost_alpha: Optional[float] = None
    cost_beta: Optional[float] = None
    # 편도 우회 품질 진단값. 기존 호출자는 기본값으로 하위 호환된다.
    selection_status: Optional[str] = None
    target_distance_error_km: Optional[float] = None
    candidate_unique_count: int = 1
    candidate_duplicate_ratio: float = 0.0
    route_seed: Optional[int] = None
