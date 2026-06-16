from pydantic import BaseModel

class CircularRouteInput(BaseModel):
    """
    순환 경로 생성 엔진의 입력 구조입니다.
    """
    start_lat: float
    start_lon: float
    target_km: float | None = None


class OnewayRouteInput(BaseModel):
    """
    편도 경로 생성 엔진의 입력 구조입니다.
    """
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    target_km: float | None = None


class EngineWeights(BaseModel):
    """
    가중치 구조입니다.
    사용하지 않는 feature는 None으로 둡니다.
    """
    safety: float | None = None
    nature: float | None = None
    slope:  float | None = None


class RouteOutput(BaseModel):
    """
    경로 생성 엔진의 출력 구조입니다.
    """
    mode: str
    coordinates: list[list[float]]          # [[lat, lon], ...]
    error: str | None = None
