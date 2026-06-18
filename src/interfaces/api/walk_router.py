import traceback

from fastapi import APIRouter, Depends, HTTPException

from src.interfaces.dependencies import get_route_service
from src.interfaces.schema.walk_schema import (
    WalkRouteRequest,
    WalkRouteResponse
)
from src.service.route.route_service import RouteService

from src.service.route.route_request_builder import RouteRequestBuilder

router = APIRouter(
    prefix="/api/walk",
    tags=["walk"],
)

@router.post("/route", response_model=WalkRouteResponse)
async def walk_route(
    request: WalkRouteRequest,
    service: RouteService = Depends(get_route_service),
):
    """
    산책 경로를 추천합니다.
    """
    try:
        safe_args = RouteRequestBuilder.build(request)
        return service.get_route(
            safe_args["origin"], 
            safe_args["destination"], 
            safe_args["target_km"], 
            safe_args["mode"]
        )
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))