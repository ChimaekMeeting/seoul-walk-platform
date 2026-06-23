from fastapi import APIRouter, Depends, HTTPException
from src.database.postgresql import get_postgresql_db
from src.interfaces.schema.prewalk_schema import InitRequest, ChatRequest, ChatResponse
from src.interfaces.validators.coord_validator import validate_seoul_polygon_contains
from src.interfaces.validators.highway_validator import validate_no_highway
from src.interfaces.validators.water_validator import snap_coordinate_from_water
from src.service.chat.prewalk_service import PrewalkOrchestrator
from src.interfaces.dependencies import get_prewalk_orchestrator

router = APIRouter(
    prefix="/api/prewalk",
    tags=["prewalk"]
)

@router.post("/init", response_model=ChatResponse)
async def read_init_message(
    request: InitRequest,
    service: PrewalkOrchestrator = Depends(get_prewalk_orchestrator)
):
    """
    산책 추천 챗봇의 첫 번째 메시지입니다.
    현재 좌표의 날씨 정보를 분석하여 환영 인사를 반환합니다.
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

        return await service.get_init_message(request.user_uuid, lat, lon)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/intent", response_model=ChatResponse)
async def read_message(
    request: ChatRequest,
    service: PrewalkOrchestrator = Depends(get_prewalk_orchestrator)
):
    """
    사용자가 메시지를 보낼 때마다 호출됩니다.
    """
    return await service.orchestrator(request.thread_id, request.user_prompt)