import httpx
from dotenv import load_dotenv
import os
from typing import Optional
from urllib.parse import urlencode

from src.service.user.user_service import UserService
from src.service.user.auth_service import AuthService
from src.infrastructure.cache.repository.user_repository import UserRepository as CacheUserRepository
from src.interfaces.schema.login_schema import LoginUrlResponse
from src.interfaces.schema.auth_schema import Status
from src.entity.user import Provider

load_dotenv()

class KakaoLoginService:
    def __init__(self, user_service: UserService, auth_service: AuthService):
        self.KAKAO_API_KEY = os.getenv("KAKAO_API_KEY")
        self.REDIRECT_URI = os.getenv("KAKAO_REDIRECT_URI")

        self.user_service = user_service
        self.auth_service = auth_service

    def get_login_url(self) -> LoginUrlResponse:
        """
        카카오 OAuth 로그인 URL을 생성해 반환합니다.
        """
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
            token_data = res.json()

            # 인가 코드 만료/재사용/redirect_uri 불일치 등으로 교환이 실패하면
            # 카카오 에러 페이로드를 그대로 드러내 원인을 알 수 있게 합니다.
            access_token = token_data.get("access_token")
            if access_token is None:
                raise ValueError(f"카카오 토큰 발급 실패: {token_data}")

            return access_token
        
    async def get_user_info(self, access_token: str):
        """
        카카오 access_token으로 사용자 정보를 조회합니다.
        """
        url = "https://kapi.kakao.com/v2/user/me"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/x-www-form-urlencoded;charset=utf-8"
        }

        async with httpx.AsyncClient() as client:
            user_res = await client.get(url, headers=headers)
            user_data = user_res.json()

            # id가 없으면 토큰 교환 실패 등으로 사용자 정보 조회가 실패한 것이므로
            # 카카오 응답 페이로드를 그대로 드러내 원인을 알 수 있게 합니다.
            if "id" not in user_data:
                raise ValueError(f"카카오 사용자 정보 조회 실패: {user_data}")

            provider_id = str(user_data.get("id"))

            # 동의항목(profile_nickname) 미설정 시 nickname이 없을 수 있으므로 안전하게 파싱합니다.
            kakao_account = user_data.get("kakao_account") or {}
            profile = kakao_account.get("profile") or {}
            nickname = profile.get("nickname")

            return provider_id, nickname
        
    async def login(self, code: str):
        """
        로그인을 진행합니다.
        """
        kakao_access_token = await self.get_access_token(code)
        provider_id, nickname = await self.get_user_info(kakao_access_token)

        jwt_access_token = self.auth_service.get_access_token(Provider.KAKAO, provider_id)
        jwt_refresh_token = self.auth_service.get_refresh_token(Provider.KAKAO, provider_id)

        user = await self.user_service.save(Provider.KAKAO, provider_id, jwt_refresh_token, nickname)
        
        return jwt_access_token, jwt_refresh_token, nickname


    async def logout(self, access_token: Optional[str], refresh_token: Optional[str]):
        """
        DB의 refresh_token을 제거하여 완전히 로그아웃합니다.
        """
        provider_id = None

        if access_token:
            status, _, pid = self.auth_service.check_access_token(access_token)
            if status == Status.SUCCESS:
                provider_id = pid

        if provider_id is None and refresh_token:
            status, _, pid = await self.auth_service.check_refresh_token(refresh_token)
            if status == Status.SUCCESS:
                provider_id = pid

        if provider_id is not None:
            await CacheUserRepository.delete_refresh_token(Provider.KAKAO, provider_id)