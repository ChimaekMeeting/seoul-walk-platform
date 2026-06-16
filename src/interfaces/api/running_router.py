import traceback

from fastapi import APIRouter, HTTPException

from src.interfaces.schema.running_schema import (
    CircularRunningRequest,
    CircularRunningResponse,
    OnewayRunningRequest,
    OnewayRunningResponse,
)
from src.route_engine.engines.circular.running import get_circular_route
from src.route_engine.engines.oneway.running import get_oneway_route

router = APIRouter(
    prefix="/api/running",
    tags=["running"],
)

@router.post("/circular", response_model=CircularRunningResponse)
async def circular_running(request: CircularRunningRequest):
    """
    출발점 기준 순환(루프) 런닝 코스를 추천합니다.
    """
    try:
        return get_circular_route(
            lat=request.lat,
            lon=request.lon,
            target_km=request.target_km,
            radius_m=request.radius_m,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/oneway", response_model=OnewayRunningResponse)
async def oneway_running(request: OnewayRunningRequest):
    """
    출발점에서 도착점까지 편도 런닝 코스를 추천합니다.
    """
    try:
        return get_oneway_route(
            start_lat=request.start_lat,
            start_lon=request.start_lon,
            end_lat=request.end_lat,
            end_lon=request.end_lon,
            target_km=request.target_km,
            use_random=request.use_random,
            radius_m=request.radius_m,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))