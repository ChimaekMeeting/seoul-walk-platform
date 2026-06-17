import traceback

from fastapi import APIRouter, Depends, HTTPException

from src.interfaces.dependencies import get_route_service
from src.interfaces.schema.walk_schema import WalkRouteRequest, WalkRouteResponse
from src.service.route.route_service import RouteService

router = APIRouter(
    prefix="/api/walk",
    tags=["walk"],
)


@router.post("/route", response_model=WalkRouteResponse)
async def walk_route(
    request: WalkRouteRequest,
    service: RouteService = Depends(get_route_service),
):
    """출발지 기반 산책 경로를 추천합니다."""
    try:
        start_lat   = request.origin.coordinate.lat
        start_lon   = request.origin.coordinate.lon
        distance_km = request.distance_km

        # profile_name 정규화
        profile_name = request.profile_name.lower().strip() if request.profile_name else "default"

        # child_friendly 플래그 또는 profile_name이 child이면 child 전용 모드로 라우팅
        mode = request.mode
        if request.child_friendly or profile_name == "child":
            mode = "circular_child" if mode == "circular_random" else "oneway_child"

        context = {
            "mode":         mode,
            "distance_km":  distance_km,
            "profile_name": profile_name,
            "origin": {
                "place_name": request.origin.place_name,
                "address":    request.origin.address,
                "coordinate": {"lat": start_lat, "lon": start_lon},
            },
            "destination": (
                {
                    "place_name": request.destination.place_name,
                    "address":    request.destination.address,
                    "coordinate": {
                        "lat": request.destination.coordinate.lat,
                        "lon": request.destination.coordinate.lon,
                    },
                }
                if request.destination else None
            ),
            "purpose": request.purpose,
        }

        output = service.get_route(context)
        return WalkRouteResponse(
            mode              = output.mode,
            coordinates       = output.coordinates,
            total_distance_km = output.total_km,
            error             = output.fallback_reason.value if output.fallback_reason else None,
        )

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
