from fastapi import APIRouter, Depends, Cookie
from src.interfaces.schema.prewalk_schema import InitRequest, ChatRequest, ChatResponse
from src.service.chat.prewalk_service import PrewalkOrchestrator
from src.interfaces.dependencies import get_prewalk_orchestrator

router = APIRouter(
    prefix="/api/prewalk",
    tags=["prewalk"]
)

@router.post("/init", response_model=ChatResponse)
async def read_init_message(
    request: InitRequest,
    access_token: str = Cookie(None),
    service: PrewalkOrchestrator = Depends(get_prewalk_orchestrator)
):
    """
    산책 추천 챗봇의 첫 번째 메시지입니다.
    현재 좌표의 날씨 정보를 분석하여 환영 인사를 반환합니다.
    """
    return await service.get_init_message(access_token, request.lat, request.lon)

@router.post("/intent", response_model=ChatResponse)
async def read_message(
    request: ChatRequest,
    access_token: str = Cookie(None),
    service: PrewalkOrchestrator = Depends(get_prewalk_orchestrator)
):
    """
    사용자가 메시지를 보낼 때마다 호출됩니다.
    """
    return await service.orchestrator(access_token, request.thread_id, request.user_prompt)