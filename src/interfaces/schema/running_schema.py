from typing import Optional
from pydantic import BaseModel


class CourseInfo(BaseModel):
    id:                     int
    name:                   str
    course_type:            str
    difficulty:             Optional[str] = None
    start_lat:              float
    start_lon:              float
    distance_from_origin_m: float


class OnewayRunningResponse(BaseModel):
    courses:    list[CourseInfo] = []
    total_km:   float = 0.0
    mode:       str   = "oneway_running"


RUNNING_COURSE_TYPES = ["river", "park", "bike_track", "trail"]
