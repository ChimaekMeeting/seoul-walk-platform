from uuid import uuid4
from dotenv import load_dotenv
import os, httpx, jwt
from datetime import datetime, timedelta, timezone

from src.repository.user_repository import UserRepository
from src.schema.user_schema import KakaoLoginUrlResponse

load_dotenv()

class UserService:
    @staticmethod
    def save_and_get_uuid():
        """
        사용자의 uuid를 저장 후 반환합니다.
        """
        user_uuid = str(uuid4())
        UserRepository.save(user_uuid)
        return user_uuid

class KakaoLoginService:
    def __init__(self):
        self.KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")
        self.KAKAO_REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI")

        self.SECRET_KEY = os.getenv("SECRET_KEY")
        self.ALGORITHM = "HS256"
        self.ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 하루 동안 유효하도록 설정

    def get_url(self) -> KakaoLoginUrlResponse:
        base_url = "https://kauth.kakao.com/oauth/authorize"
        kakao_login_url = (
            f"{base_url}?client_id={self.KAKAO_API_KEY}"
            f"&redirect_uri={self.KAKAO_REDIRECT_URI}"
            f"&response_type=code"
        )
        return KakaoLoginUrlResponse(kakao_login_url=kakao_login_url)
    
    async def get_access_token(self, code: str):
        base_url = "https://kauth.kakao.com/oauth/token"
        headers = {
            "Content_Type": "application/x-www-form-urlencoded;charset=utf-8"
        }
        params = {
            "grant_type": "authorization_code",
            "client_id": self.KAKAO_API_KEY,
            "redirect_uri": self.KAKAO_REDIRECT_URI,
            "code": code
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(base_url, headers=headers, params=params)
            data = res.json()

            return data.get("access_token"), data.get("refresh_token")
        
    async def get_user_info(self, access_token: str):
        base_url = "https://kapi.kakao.com/v2/user/me"
        headers = {
            "Authorization": f"Bearer ${access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
        }

        async with httpx.AsyncClient() as client:
            res = await client.get(base_url, headers=headers)
            data = res.json()

        return data.get("id"), data.get("profile").get("nickname")
    
    def create_jwt_token(self, provider_id: int) -> str:
        """
        서비스 전용 Access Token을 생성합니다.
        """
        expire = datetime.now(timezone.utc) + timedelta(minutes=self.ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode = {
            "sub": str(provider_id),
            "exp": expire
        }

        encoded_jwt = jwt.encode(to_encode, self.SECRET_KEY, algorithm=self.ALGORITHM)
        return encoded_jwt
    
    async def login(self, code: str):
        access_token, refresh_token = await self.get_access_token(code)
        provider_id, nickname = await self.get_user_info(access_token)

        return nickname

    async def logout(self, kakao_access_token: str) -> int:
        """
        카카오 서버에 로그아웃을 요청하고 해당 사용자의 provider_id를 반환합니다.
        """
        base_url = "https://kapi.kakao.com/v1/user/logout"
        headers = {
            "Authorization": f"Bearer {kakao_access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(base_url, headers=headers)
            data = res.json()

        return data.get("id")

