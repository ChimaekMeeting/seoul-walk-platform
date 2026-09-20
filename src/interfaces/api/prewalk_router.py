import logging

from fastapi import APIRouter, Depends, HTTPException
from src.database.postgresql import get_postgresql_db
from src.interfaces.schema.prewalk_schema import InitRequest, ChatRequest, ChatResponse
from src.interfaces.validators.coord_validator import validate_seoul_polygon_contains
from src.interfaces.validators.highway_validator import validate_no_highway
from src.interfaces.validators.water_validator import snap_coordinate_from_water
from src.service.chat.prewalk_service import PrewalkOrchestrator
from src.interfaces.dependencies import get_prewalk_orchestrator
from src.interfaces.errors import SAFE_INTERNAL_ERROR_DETAIL, log_unexpected_error
from src.interfaces.security import resolve_access_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/prewalk",
    tags=["prewalk"]
)

@router.post(
    "/init",
    response_model=ChatResponse,
    response_model_exclude={"state": {"access_token"}},
    responses={
        400: {"description": "PostGIS 영역·도로·수계 검증 등 요청 좌표 오류"},
        401: {"description": "Authorization 헤더 형식 오류"},
        422: {"description": "요청 스키마·좌표 제약 오류"},
        500: {"description": "안전한 공통 메시지로 반환하는 예기치 않은 서버 오류"},
    },
)
async def read_init_message(
    request: InitRequest,
    access_token: str | None = Depends(resolve_access_token),
    service: PrewalkOrchestrator = Depends(get_prewalk_orchestrator)
):
    """
    산책 추천 챗봇의 첫 번째 메시지입니다.
    현재 좌표의 날씨 정보를 분석하여 환영 인사를 반환합니다. ROUDI access token은
    Bearer를 우선하며, 없으면 기존 access_token cookie를 사용합니다.
    """
    try:
        with get_postgresql_db() as db:
            # VAL-COORD-004 2차: PostGIS 폴리곤 정밀 검증
            validate_seoul_polygon_contains(request.lat, request.lon, db)

            # VAL-COORD-005: 수계 위 좌표 → 가장 가까운 보행 노드로 Snap
            lat, lon = snap_coordinate_from_water(request.lat, request.lon, db)

            # VAL-COORD-006: 고속도로/전용도로 위 좌표 차단 (원래 좌표 기준, 수계 snap 시 생략)
            if lat == request.lat and lon == request.lon:
                validate_no_highway(request.lat, request.lon, db)

        return await service.get_init_message(access_token, lat, lon)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_unexpected_error(logger, "prewalk_init_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e

@router.post(
    "/intent",
    response_model=ChatResponse,
    response_model_exclude={"state": {"access_token"}},
    responses={
        400: {"description": "요청 처리 중 확인된 입력 오류"},
        401: {"description": "Authorization 헤더 형식 오류"},
        422: {"description": "요청 스키마·좌표·메시지 제약 오류"},
        500: {"description": "안전한 공통 메시지로 반환하는 예기치 않은 서버 오류"},
    },
)
async def read_message(
    request: ChatRequest,
    access_token: str | None = Depends(resolve_access_token),
    service: PrewalkOrchestrator = Depends(get_prewalk_orchestrator)
):
    """
    사용자가 메시지를 보낼 때마다 호출됩니다. 인증 입력 우선순위는 init과 같습니다.
    """
    try:
        return await service.orchestrator(
            access_token, request.thread_id, request.user_prompt, request.lat, request.lon
        )
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log_unexpected_error(logger, "prewalk_intent_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e
