import httpx
from dotenv import load_dotenv
import os
from typing import Optional
from urllib.parse import urlencode

from src.service.user_service import UserService
from src.service.auth_service import AuthService
from src.repository.user.user_repository import UserRepository
from src.interfaces.schema.login_schema import LoginUrlResponse
from src.interfaces.schema.auth_schema import Status

load_dotenv()

class KakaoLoginService:
    def __init__(self, user_service: UserService, auth_service: AuthService):
        self.KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")
        self.REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI")

        self.user_service = user_service
        self.auth_service = auth_service

    def get_login_url(self) -> LoginUrlResponse:
        base_url = "https://kauth.kakao.com/oauth/authorize"

        params = {
            "client_id": self.KAKAO_API_KEY,
            "redirect_uri": self.REDIRECT_URI,
            "response_type": "code",
            "lang": "ko",
        }

        query_string = urlencode(params)

        return f"{base_url}?{query_string}"
    
    async def get_access_token(self, code: str):
        """
        인가코드를 access_token으로 교환합니다.
        """
        url = "https://kauth.kakao.com/oauth/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded;charset=utf-8"}
        data = {
            "grant_type": "authorization_code",
            "client_id": self.KAKAO_API_KEY,
            "redirect_uri": self.REDIRECT_URI,
            "code": code,
        }

        async with httpx.AsyncClient() as client:
            res = await client.post(url, headers=headers, data=data)
            data = res.json()

            return data.get("access_token")
        
    async def get_user_info(self, access_token: str):
        url = "https://kapi.kakao.com/v2/user/me"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
        }

        async with httpx.AsyncClient() as client:
            user_res = await client.get(url, headers=headers)
            user_data = user_res.json()

            provider_id = user_data.get("id")
            nickname = user_data.get("kakao_account").get("profile").get("nickname")

            return provider_id, nickname
        
    async def login(self, code: str):
        """
        로그인을 진행합니다.
        """
        access_token = await self.get_access_token(code)
        provider_id, nickname = await self.get_user_info(access_token)

        jwt_access_token = self.auth_service.get_access_token(provider_id)
        jwt_refresh_token = self.auth_service.get_refresh_token(provider_id)

        # user = self.user_service.login(provider_id, jwt_refresh_token, nickname)
        
        return jwt_access_token, jwt_refresh_token, nickname, None


    # def logout(self, access_token: Optional[str], refresh_token: Optional[str]):
    #     """
    #     DB의 refresh_token을 제거합니다. 토큰이 모두 유효하지 않아도 쿠키는 클라이언트에서 제거됩니다.
    #     """
    #     provider_id = None

    #     if access_token:
    #         status, pid = self.auth_service.check_access_token(access_token)
    #         if status == Status.SUCCESS:
    #             provider_id = pid

    #     if provider_id is None and refresh_token:
    #         status, _, pid = self.auth_service.check_refresh_token(refresh_token)
    #         if status == Status.SUCCESS:
    #             provider_id = pid

    #     if provider_id is not None:
    #         UserRepository.clear_refresh_token(provider_id)