from pydantic import BaseModel

from src.interfaces.schema.user_schema import UserResponse

class LoginUrlResponse(BaseModel):
    """
    OAuth 로그인을 위한 리다이렉트 URL을 제공하는 응답 스키마입니다.
    """
    url: str

class LoginResponse(UserResponse):
    """
    로그인 처리 결과를 담는 응답 스키마입니다.
    """
    token_type: str = "Bearer"