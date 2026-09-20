from pydantic import BaseModel, ConfigDict, Field

from src.interfaces.schema.user_schema import UserResponse

class LoginUrlResponse(BaseModel):
    url: str

class LoginResponse(UserResponse):
    token_type: str = Field(default="Bearer", description="ROUDI JWT 전달 방식")
    access_token: str = Field(description="ROUDI API 호출용 access token (기본 만료 1시간)")
    refresh_token: str = Field(description="access token 재발급 및 로그아웃용 refresh token (기본 만료 14일)")

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


class LogoutRequest(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={"example": {"refresh_token": "roudi-refresh-token"}}
    )

    refresh_token: str = Field(
        min_length=1,
        pattern=r"\S",
        repr=False,
        description=(
            "ROUDI 로그인 응답에서 받은 refresh token입니다. Kakao SDK token이 아닙니다. "
            "access token이 만료되거나 없어도 서버 저장값과 일치하면 로그아웃할 수 있습니다. "
            "본문을 보내면 refresh cookie 대신 이 값을 사용합니다."
        ),
    )
