from fastapi import APIRouter, Depends
from src.interfaces.dependencies import get_user_service
from src.interfaces.schema.user_schema import UuidResponse
from src.service.user_service import UserService

router = APIRouter(
    prefix="/api/user",
    tags=["user"]
)

@router.post("/init", response_model=UuidResponse)
def read_init(
    service: UserService = Depends(get_user_service)
):
    """
    서비스에 처음 방문한 유저에게 uuid를 제공합니다.
    """
    user_uuid = service.save_and_get_uuid()
    return UuidResponse(user_uuid=user_uuid)