from enum import Enum
from math import atan2, cos, degrees, radians, sin
from pydantic import BaseModel, Field, RootModel, field_validator, model_validator
from pydantic.json_schema import SkipJsonSchema
from typing import Literal, Optional, Union, List
from src.interfaces.schema.maneuver_schema import ManeuverType, RouteManeuver
from src.interfaces.schema.walk_schema import WalkMode, WalkRouteResponse
from src.interfaces.validators.dist_validator import validate_target_km_positive


class ManeuverType(str, Enum):
    START = "start"
    STRAIGHT = "straight"
    LEFT = "left"
    RIGHT = "right"
    U_TURN = "u_turn"
    ARRIVE = "arrive"


class RouteManeuver(BaseModel):
    sequence: int = Field(ge=0)
    type: ManeuverType
    instruction: str = Field(min_length=1)
    lat: float
    lon: float
    node_id: Optional[int] = None
    distance_from_start_m: float = Field(ge=0.0)
    distance_to_maneuver_m: float = Field(ge=0.0)
    bearing_before_deg: Optional[float] = Field(default=None, ge=0.0, lt=360.0)
    bearing_after_deg: Optional[float] = Field(default=None, ge=0.0, lt=360.0)
    turn_angle_deg: Optional[float] = Field(default=None, ge=0.0, le=180.0)


class RouteGeometry(BaseModel):
    node_ids: list[int] = Field(default_factory=list)
    coordinates: list[list[float]] = Field(default_factory=list)


class ChatbotRouteDetails(BaseModel):
    geometry: RouteGeometry = Field(default_factory=RouteGeometry)
    maneuvers: list[RouteManeuver] = Field(default_factory=list)


def _bearing_deg(start: list[float], end: list[float]) -> Optional[float]:
    if len(start) < 2 or len(end) < 2 or start == end:
        return None

    lat1 = radians(start[0])
    lat2 = radians(end[0])
    delta_lon = radians(end[1] - start[1])
    x = sin(delta_lon) * cos(lat2)
    y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(delta_lon)
    return (degrees(atan2(x, y)) + 360.0) % 360.0


def _turn_angle_deg(
    before: Optional[float],
    after: Optional[float],
) -> Optional[float]:
    if before is None or after is None:
        return None
    difference = abs(after - before)
    return min(difference, 360.0 - difference)


def _maneuver_type(
    before: Optional[float],
    after: Optional[float],
    angle: Optional[float],
) -> ManeuverType:
    if before is None:
        return ManeuverType.START
    if after is None:
        return ManeuverType.ARRIVE
    if angle is not None and angle >= 135.0:
        return ManeuverType.U_TURN
    delta = (after - before + 360.0) % 360.0
    return ManeuverType.RIGHT if delta < 180.0 else ManeuverType.LEFT


def build_route_maneuvers(
    node_ids: list[int],
    coordinates: list[list[float]],
    distance_from_start_m: Optional[list[float]] = None,
) -> list[RouteManeuver]:
    if not coordinates:
        return []
    if len(node_ids) != len(coordinates):
        raise ValueError("node_ids와 coordinates의 길이가 다릅니다.")

    distances = distance_from_start_m or [0.0] * len(coordinates)
    if len(distances) != len(coordinates):
        raise ValueError("distance_from_start_m과 coordinates의 길이가 다릅니다.")

    bearings = [
        _bearing_deg(coordinates[index], coordinates[index + 1])
        for index in range(len(coordinates) - 1)
    ]
    maneuvers: list[RouteManeuver] = []

    for index, coordinate in enumerate(coordinates):
        before = bearings[index - 1] if index > 0 else None
        after = bearings[index] if index < len(bearings) else None
        angle = _turn_angle_deg(before, after)

        if 0 < index < len(coordinates) - 1 and (angle is None or angle < 30.0):
            continue

        if index == 0:
            maneuver_type = ManeuverType.START
            instruction = "출발하세요."
        elif index == len(coordinates) - 1:
            maneuver_type = ManeuverType.ARRIVE
            instruction = "도착했습니다."
        else:
            maneuver_type = _maneuver_type(before, after, angle)
            instruction = "방향을 전환하세요."

        previous_distance = distances[index - 1] if index > 0 else distances[index]
        maneuvers.append(
            RouteManeuver(
                sequence=len(maneuvers),
                type=maneuver_type,
                instruction=instruction,
                lat=coordinate[0],
                lon=coordinate[1],
                node_id=node_ids[index],
                distance_from_start_m=distances[index],
                distance_to_maneuver_m=max(0.0, distances[index] - previous_distance),
                bearing_before_deg=before,
                bearing_after_deg=after,
                turn_angle_deg=angle,
            )
        )

    return maneuvers


class TargetKmPositiveMixin(BaseModel):
    """
    target_km 필드가 있는 Preference가 공용으로 쓰는 하한 검증.
    직접 경로 API(WalkRouteRequest, VAL-DIST-001)와 같은 validate_target_km_positive를
    재사용해 0 이하 값을 차단한다 — 기준을 두 입구에서 따로 정의하지 않는다.
    """
    @field_validator("target_km", mode="before", check_fields=False)
    @classmethod
    def _check_target_km_positive(cls, value: object) -> object:
        return validate_target_km_positive(value)


class Location(BaseModel):
    """
    위치(출발지, 목적지) 관련 정보입니다.
    """
    lat: Optional[float] = Field(None, description="위도(Latitude)")
    lon: Optional[float] = Field(None, description="경도(Longitude)")
    address: Optional[str] = Field(None, description="지번 주소 또는 도로명 주소")
    place_name: Optional[str] = Field(None, description="장소 명칭")

    @model_validator(mode="before")
    @classmethod
    def _coerce_bare_string(cls, value):
        """
        LLM이 Location 대신 장소명 문자열만 넘기는 경우, place_name으로 감싸 받아들인다.
        (예: origin="홍대" -> Location(place_name="홍대"))
        """
        if isinstance(value, str):
            return {"place_name": value}
        return value


class BasePreference(BaseModel):
    origin: Optional[Location] = None


class CircularPreference(BasePreference, TargetKmPositiveMixin):
    """
    순환 경로(circular_random)일 때 채워야 할 필수 정보입니다.
    """
    mode:      WalkMode = WalkMode.CIRCULAR_RANDOM
    target_km: Optional[float] = None


class OnewayPreference(BasePreference, TargetKmPositiveMixin):
    """
    편도 우회 경로(oneway_random)일 때 채워야 할 필수 정보입니다.
    """
    mode:        WalkMode = WalkMode.ONEWAY_RANDOM
    destination: Optional[Location] = None
    target_km:   Optional[float]    = None


class OnewayShortestPreference(BasePreference):
    """
    다익스트라 기반 최단 편도 경로(oneway_shortest)일 때 채워야 할 필수 정보입니다.
    """
    mode:        WalkMode = WalkMode.ONEWAY_SHORTEST
    destination: Optional[Location] = None


class GPSArtPreference(BasePreference, TargetKmPositiveMixin):
    """
    GPS Art 기반 경로일 때 채워야 할 필수 정보입니다.
    """
    mode:      WalkMode = WalkMode.GPS_ART
    shape:     Optional[str] = None
    target_km: Optional[float] = None


WaypointLegMode = Literal["oneway_shortest", "oneway_random"]


class WaypointLegPreference(TargetKmPositiveMixin):
    """
    경유지 구간(leg) 하나의 이동 방식입니다. 언급이 없으면 최단 경로로 간주합니다.
    """
    mode:      WaypointLegMode = "oneway_shortest"
    target_km: Optional[float] = None  # mode가 oneway_random일 때만 사용


class WayPointPreference(BasePreference):
    """
    경유지를 거쳐가는 경로일 때 채워야 할 필수 정보입니다.
    origin -> waypoints[0] -> ... -> waypoints[-1] -> destination 순으로 이동하며,
    legs[i]가 그 순서상 i번째 구간의 이동 방식입니다(길이는 waypoints 길이 + 1).
    순환 코스를 원하면 destination을 origin과 동일한 위치로 설정합니다.
    """
    mode:        WalkMode = WalkMode.WAYPOINT
    waypoints:   List[Location] = Field(default_factory=list)
    destination: Optional[Location] = None
    legs:        List[WaypointLegPreference] = Field(default_factory=list)


class FeatureTag(str, Enum):
    """
    가중치 라벨링 대상이 되는 선호 특징 축입니다. 새 feature가 늘어나면 여기에 값을
    추가합니다 — RouteExecutor가 Weights 필드로 매핑할 때도 이 값을 키로 씁니다.
    """
    SAFETY  = "safety"
    COMFORT = "comfort"


ExplicitnessLabel = Literal["explicit_hard", "explicit_soft", "optional", "inferred"]
PreferenceLabel   = Literal["must", "high", "neutral", "low"]

class FeatureLabel(BaseModel):
    """
    개별 feature에 대한 명시적 라벨과 선호도 라벨입니다.
    """
    preference_label:   PreferenceLabel
    explicitness_label: ExplicitnessLabel


# 이번 턴 WeightExtractor가 그 축에 대해 실제로 낼 수 있는 값. "cancelled"는 [이전 라벨]에
# 있던 값을 대체 없이 명시적으로 취소한다는 뜻이고, dict에 그 축의 키 자체가 없는 것은
# 이번 발화가 그 축을 아예 다루지 않았다는 뜻이다(이전 값 유지) — 이 둘을 구분하려고
# 만든 타입이다(WeightExtractor.run()의 병합 로직 참고).
FeatureLabelEntry = Union[FeatureLabel, Literal["cancelled"]]


class FeatureLabelMap(RootModel[dict[FeatureTag, FeatureLabelEntry]]):
    """
    WeightExtractor 출력 전체를 감싸는 root model입니다. PydanticOutputParser는
    BaseModel만 파싱 대상으로 받을 수 있어 dict[FeatureTag, FeatureLabelEntry]를 직접
    쓸 수 없으므로 RootModel로 감쌉니다.
    """


class State(BaseModel):
    """
    대화 상태 관련 정보입니다.
    """
    user_id: int
    current_location: Location
    access_token: SkipJsonSchema[Optional[str]] = Field(
        default=None,
        description="현재 Graph 실행에서만 사용하는 내부 access token",
    )

    mode: Optional[WalkMode] = None
    user_context: Optional[
        Union[
            CircularPreference,
            OnewayPreference,
            OnewayShortestPreference,
            GPSArtPreference,
            WayPointPreference,
        ]
    ] = None

    origin_candidate: Optional[List[Location]] = None
    destination_candidate: Optional[List[Location]] = None
    waypoint_candidates: Optional[List[Optional[List[Location]]]] = None

    route_result: Optional[List[WalkRouteResponse]] = None
    chatbot_route_details: Optional[ChatbotRouteDetails] = None
    shortest_km: Optional[float] = None  # 최단 경로, 편도 우회에서만 채워지는 값
    is_complete: bool = False
    awaiting_confirmation: bool = False
    user_prompt: str  = ""
    response:    str  = ""
    feature_labels: dict[FeatureTag, FeatureLabel] = Field(default_factory=dict)  # feature별 명시적 라벨, 선호도 라벨

    def model_dump_for_storage(self) -> dict:
        """Valkey 저장 시 내부 access token을 제외한 JSON 호환 상태를 반환합니다."""
        return self.model_dump(mode="json", exclude={"access_token"})
