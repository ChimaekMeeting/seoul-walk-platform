import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException

from src.database.postgresql import get_postgresql_db
from src.interfaces.dependencies import get_route_service
from src.interfaces.errors import SAFE_INTERNAL_ERROR_DETAIL, log_unexpected_error
from src.interfaces.security import resolve_access_token
from src.interfaces.schema.walk_schema import (
    Coordinate,
    WalkRouteRequest,
    WalkRouteResponse,
    WalkRouteStatus,
)
from src.interfaces.validators.coord_validator import validate_seoul_polygon_contains
from src.interfaces.validators.highway_validator import validate_no_highway
from src.interfaces.validators.water_validator import snap_coordinate_from_water
from src.service.route.route_service import RouteService
from src.config.settings import settings

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/walk",
    tags=["walk"],
)

@router.post(
    "/route",
    response_model=WalkRouteResponse,
    responses={
        400: {"description": "PostGIS 영역·도로·수계 검증 등 요청 좌표 오류"},
        401: {"description": "Authorization 헤더 형식 오류"},
        422: {"description": "요청 스키마·좌표·거리 제약 오류"},
        500: {"description": "안전한 공통 메시지로 반환하는 예기치 않은 서버 오류"},
    },
)
async def walk_route(
    request: WalkRouteRequest,
    access_token: str | None = Depends(resolve_access_token),
    service: RouteService = Depends(get_route_service),
):
    """
    산책 경로를 추천합니다. ROUDI access token은 Bearer를 우선하며, 없으면
    기존 access_token cookie를 사용합니다.
    """
    logger.info("walk route request received: mode=%s", request.mode)
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

        results = await asyncio.wait_for(
            asyncio.to_thread(
                service.get_route,
                access_token, origin, destination, request.target_km, request.mode,
                seed=request.seed,
            ),
            timeout=settings.WALK_ROUTE_HARD_TIMEOUT_SEC,
        )
        # RouteService.get_route()는 06fc3b1(경로 N개 생성 리팩토링) 이후 List[WalkRouteResponse]를
        # 반환하도록 바뀌었지만 이 라우터는 아직 단일 응답 계약(response_model=WalkRouteResponse)에
        # 맞춰져 있지 않았다 — results[0](대표 후보)만 반환해 기존 계약을 유지한다.
        response = results[0]
        logger.info("walk route response completed: mode=%s status=%s", request.mode, response.status.value)
        return response
    except asyncio.TimeoutError:
        logger.warning(
            "walk route hard timeout: mode=%s timeout_sec=%.1f",
            request.mode, settings.WALK_ROUTE_HARD_TIMEOUT_SEC,
        )
        return WalkRouteResponse(
            status=WalkRouteStatus.TIMEOUT,
            mode=request.mode,
            coordinates=[],
            total_km=0.0,
            selection_status="timeout",
            route_seed=request.seed if request.seed is not None else 42,
        )
    except HTTPException:
        raise
    except ValueError as e:
        logger.warning("walk route invalid request: mode=%s error=%s", request.mode, e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_unexpected_error(logger, "walk_route_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e
