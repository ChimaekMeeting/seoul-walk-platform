from pydantic import BaseModel

class UuidResponse(BaseModel):
    """
    신규 사용자에게 고유 식별자(UUID)를 제공하는 모델입니다.
    """
    user_uuid: str