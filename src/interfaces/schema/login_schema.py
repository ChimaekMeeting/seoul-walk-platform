from pydantic import BaseModel, ConfigDict, Field

from src.interfaces.schema.user_schema import UserResponse

class LoginUrlResponse(BaseModel):
    url: str

class LoginResponse(UserResponse):
    token_type: str = Field(default="Bearer", description="ROUDI JWT 전달 방식")
    access_token: str = Field(description="ROUDI API 호출용 access token (기본 만료 1시간)")
    refresh_token: str = Field(description="access token 재발급 전용 refresh token (기본 만료 14일)")

class MobileLoginRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"access_token": "kakao-sdk-access-token"}}
    )

    access_token: str = Field(
        min_length=1,
        description=(
            "모바일 Kakao SDK가 발급한 Kakao access token입니다. "
            "ROUDI access/refresh token이 아닙니다."
        ),
    )
