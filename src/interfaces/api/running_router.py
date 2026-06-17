import traceback

from fastapi import APIRouter, HTTPException

from src.interfaces.schema.running_schema import (
    CircularRunningRequest,
    CircularRunningResponse,
    OnewayRunningRequest,
    OnewayRunningResponse,
)
from src.route_engine.engines.circular.running import CircularRunningEngine
from src.route_engine.engines.oneway.running import OnewayRunningEngine
from src.route_engine.schema import CircularRouteInput, OnewayRouteInput

router = APIRouter(prefix="/api/running", tags=["running"])


@router.post("/circular", response_model=CircularRunningResponse)
async def circular_running(request: CircularRunningRequest):
    """
    출발점 기준 순환(루프) 런닝 코스를 추천합니다.
    """
    try:
        inp    = CircularRouteInput(start_lat=request.lat, start_lon=request.lon, target_km=request.target_km)
        engine = CircularRunningEngine(inp, profile_name="running")
        output = engine.run()

        return CircularRunningResponse(
            mode               = output.mode,
            coordinates        = output.coordinates,
            total_distance_km  = output.total_km,
            matched_courses    = engine.matched_courses,
            error              = output.fallback_reason.value if output.fallback_reason else None,
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
        inp    = OnewayRouteInput(
            start_lat=request.start_lat, start_lon=request.start_lon,
            end_lat=request.end_lat,     end_lon=request.end_lon,
            target_km=request.target_km,
        )
        engine = OnewayRunningEngine(inp, profile_name="running")
        output = engine.run()

        return OnewayRunningResponse(
            mode               = output.mode,
            coordinates        = output.coordinates,
            total_distance_km  = output.total_km,
            matched_courses    = engine.matched_courses,
            error              = output.fallback_reason.value if output.fallback_reason else None,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
