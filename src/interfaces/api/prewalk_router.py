from fastapi import APIRouter, Depends
from src.interfaces.schema.prewalk_schema import InitRequest, ChatRequest, ChatResponse, Weights
from src.service.prewalk_orchestrator import PrewalkOrchestrator
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
    return await service.get_init_message(request.user_uuid, request.lat, request.lon)

@router.post("/intent", response_model=ChatResponse)
async def read_message(
    request: ChatRequest,
    service: PrewalkOrchestrator = Depends(get_prewalk_orchestrator)
):
    """
    사용자가 메시지를 보낼 때마다 호출됩니다.
    """
    return await service.orchestrator(request.thread_id, request.user_prompt)

@router.get("/weights", response_model=Weights)
async def read_weights(
    thread_id: str,
    service: PrewalkOrchestrator = Depends(get_prewalk_orchestrator)
):
    """
    사용자와 LLM 간 대화 요약본 및 날씨를 기반으로 가중치를 반환합니다.
    """
    return await service.assign_weight(thread_id)
