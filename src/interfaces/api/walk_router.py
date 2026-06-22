import traceback

from fastapi import APIRouter, Depends, HTTPException, Cookie

from src.interfaces.dependencies import get_route_service
from src.interfaces.schema.walk_schema import (
    WalkRouteRequest,
    WalkRouteResponse
)
from src.service.route.route_service import RouteService

router = APIRouter(
    prefix="/api/walk",
    tags=["walk"],
)

@router.post("/route", response_model=WalkRouteResponse)
async def walk_route(
    request: WalkRouteRequest,
    access_token: str = Cookie(None),
    service: RouteService = Depends(get_route_service),
):
    """
    산책 경로를 추천합니다.
    """
    try:
        return service.get_route(access_token, request.origin, request.destination, request.target_km, request.mode)
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))