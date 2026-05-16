from pydantic import BaseModel

class UuidResponse(BaseModel):
    """
    신규 사용자에게 고유 식별자(UUID)를 제공하는 모델입니다.
    """
    user_uuid: str

class KakaoLoginUrlResponse(BaseModel):
    """
    카카오 로그인 url 관련 스키마입니다.
    """
    kakao_login_url: str

class KakaoLoginResponse(BaseModel):
    """
    카카오 로그인 성공 응답 스키마입니다.
    """
    access_token: str
    nickname: str

class KakaoLogoutRequest(BaseModel):
    """
    카카오 로그아웃 요청 스키마입니다.
    """
    kakao_access_token: str

class KakaoLogoutResponse(BaseModel):
    """
    카카오 로그아웃 응답 스키마입니다.
    """
    message: str

class KakaoTokenRefreshRequest(BaseModel):
    """
    카카오 refresh_token으로 access_token 갱신을 요청하는 스키마입니다.
    """
    kakao_refresh_token: str