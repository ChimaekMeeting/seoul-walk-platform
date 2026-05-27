from typing import List, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────
# 공통
# ──────────────────────────────────────────────────────────────

class CourseInfo(BaseModel):
    """
    DB에서 조회된 추천 코스 요약 정보.

    ``get_courses_near()`` 반환 딕셔너리를 그대로 언팩(``**c``)해서 생성합니다.
    ``distance_from_origin_m``은 요청 출발점까지의 거리(미터)이며,
    정렬 기준으로 활용됩니다.
    """
    id: int
    name: str
    course_type: str                        # river | park | bike_track
    is_circular: bool
    distance_m: Optional[float] = None
    difficulty: Optional[str] = None
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    start_lat: float
    start_lon: float
    end_lat: Optional[float] = None
    end_lon: Optional[float] = None
    distance_from_origin_m: float           # 출발점까지 거리


# ──────────────────────────────────────────────────────────────
# 순환 코스 (Circular)
# ──────────────────────────────────────────────────────────────

class CircularRunningRequest(BaseModel):
    """
    순환 런닝 코스 요청

    출발점 좌표와 목표 거리를 받아 루프 코스를 반환합니다.
    """
    lat: float = Field(..., description="출발점 위도")
    lon: float = Field(..., description="출발점 경도")
    target_km: float = Field(5.0, ge=1.0, le=30.0, description="목표 거리 (km)")
    radius_m: float = Field(5_000, ge=500, le=20_000, description="코스 검색 반경 (미터)")


class CircularRunningResponse(BaseModel):
    """순환 런닝 코스 응답"""
    mode: str                                       # "circular_running"
    coordinates: List[List[float]]                  # [[lat, lon], ...]
    total_distance_km: float
    matched_courses: List[CourseInfo] = Field(
        default_factory=list,
        description="반경 내 DB 추천 코스 목록",
    )
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────
# 편도 코스 (Oneway)
# ──────────────────────────────────────────────────────────────

class OnewayRunningRequest(BaseModel):
    """
    편도 런닝 코스 요청.

    출발점 → 도착점 단방향 코스를 반환합니다.

    """
    start_lat: float = Field(..., description="출발점 위도")
    start_lon: float = Field(..., description="출발점 경도")
    end_lat: float   = Field(..., description="도착점 위도")
    end_lon: float   = Field(..., description="도착점 경도")
    target_km: Optional[float] = Field(
        None, ge=1.0, le=30.0,
        description="목표 거리 (km). use_random=True 일 때만 사용됩니다.",
    )
    use_random: bool = Field(
        True,
        description="True=우회 경로(더 긴 거리), False=최단 경로",
    )
    radius_m: float = Field(5_000, ge=500, le=20_000, description="코스 검색 반경 (미터)")


class OnewayRunningResponse(BaseModel):
    """편도 런닝 코스 응답"""
    mode: str                                       # "oneway_running_random" | "oneway_running_shortest"
    coordinates: List[List[float]]                  # [[lat, lon], ...]
    total_distance_km: float
    matched_courses: List[CourseInfo] = Field(
        default_factory=list,
        description="반경 내 DB 추천 코스 목록",
    )
    error: Optional[str] = None
