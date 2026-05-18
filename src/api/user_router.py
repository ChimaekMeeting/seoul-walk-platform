from fastapi import APIRouter
from src.service.user_service import UserService
from src.schema.user_schema import UuidResponse

router = APIRouter(
    prefix="/api/user",
    tags=["user"]
)

@router.post("/init", response_model=UuidResponse)
def read_init():
    """
    서비스에 처음 방문한 유저에게 uuid를 제공합니다.
    """
    user_uuid = UserService.save_and_get_uuid()
    return UuidResponse(user_uuid=user_uuid)