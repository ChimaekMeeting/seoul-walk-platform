import traceback

from fastapi import APIRouter, Depends, HTTPException, Cookie

from src.database.postgresql import get_postgresql_db
from src.interfaces.dependencies import get_route_service
from src.interfaces.schema.walk_schema import (
    Coordinate,
    WalkRouteRequest,
    WalkRouteResponse,
)
from src.interfaces.validators.coord_validator import validate_seoul_polygon_contains
from src.interfaces.validators.highway_validator import validate_no_highway
from src.interfaces.validators.water_validator import snap_coordinate_from_water
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
        with get_postgresql_db() as db:
            # VAL-COORD-004 2차: PostGIS 폴리곤 정밀 검증
            validate_seoul_polygon_contains(request.origin.lat, request.origin.lon, db)
            if request.destination is not None:
                validate_seoul_polygon_contains(request.destination.lat, request.destination.lon, db)

            # VAL-COORD-005: 수계 위 좌표 → 가장 가까운 보행 노드로 Snap
            origin_lat, origin_lon = snap_coordinate_from_water(request.origin.lat, request.origin.lon, db)

            # VAL-COORD-006: 고속도로/전용도로 위 좌표 차단 (원래 좌표 기준, 수계 snap 시 생략)
            if origin_lat == request.origin.lat and origin_lon == request.origin.lon:
                validate_no_highway(request.origin.lat, request.origin.lon, db)
            origin = Coordinate.model_construct(lat=origin_lat, lon=origin_lon)

            destination = None
            if request.destination is not None:
                dest_lat, dest_lon = snap_coordinate_from_water(
                    request.destination.lat, request.destination.lon, db
                )
                if dest_lat == request.destination.lat and dest_lon == request.destination.lon:
                    validate_no_highway(request.destination.lat, request.destination.lon, db)
                destination = Coordinate.model_construct(lat=dest_lat, lon=dest_lon)

        return service.get_route(access_token, origin, destination, request.target_km, request.mode)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))