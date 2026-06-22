from dotenv import load_dotenv
import os, jwt
from datetime import datetime, timedelta, timezone
from typing import Optional
from jwt.exceptions import ExpiredSignatureError, InvalidSignatureError, DecodeError, InvalidTokenError

from src.repository.user.user_repository import UserRepository
from src.infrastructure.cache.repository.user_repository import UserRepository as CacheUserRepository
from src.interfaces.schema.auth_schema import Status
from src.entity.user import Provider

load_dotenv()

class AuthService:
    def __init__(self):
        self.ACCESS_SECRET_KEY = os.getenv("ACCESS_SECRET_KEY")
        self.REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY")

    def get_access_token(self, provider: Provider, provider_id: str):
        """
        provider_id로 access token을 생성해 반환합니다.
        """
        now = datetime.now(timezone.utc)

        access_payload = {
            "provider": provider.value,
            "provider_id": provider_id,
            "exp": now + timedelta(minutes=60),
            "type": "access"
        }
        access_token = jwt.encode(access_payload, self.ACCESS_SECRET_KEY, algorithm="HS256")

        return access_token

    def get_refresh_token(self, provider: Provider, provider_id: str):
        """
        provider_id로 refresh token을 생성해 반환합니다.
        """
        now = datetime.now(timezone.utc)

        refresh_payload = {
            "provider": provider.value,
            "provider_id": provider_id,
            "exp": now + timedelta(days=14),
            "type": "refresh"
        }
        refresh_token = jwt.encode(refresh_payload, self.REFRESH_SECRET_KEY, algorithm="HS256")

        return refresh_token
    
    def decode(self, refresh_token: Optional[str] = None, access_token: Optional[str] = None) -> tuple[Provider, str]:
        """
        (refresh/access)token의 서명 및 만료일을 검증하고 provider_id를 반환합니다.
        """
        if refresh_token is None and access_token is None:
            raise ValueError("만료된 토큰입니다.")
        
        try:
            if refresh_token is not None:
                payload = jwt.decode(refresh_token, self.REFRESH_SECRET_KEY, algorithms=["HS256"])
                provider = payload.get("provider")
                provider_id = payload.get("provider_id")
                return Provider(provider), provider_id
            else:
                payload = jwt.decode(access_token, self.ACCESS_SECRET_KEY, algorithms=["HS256"])
                provider = payload.get("provider")
                provider_id = payload.get("provider_id")
                return Provider(provider), provider_id
        except (InvalidSignatureError, DecodeError):
            raise InvalidTokenError("유효하지 않은 토큰입니다.")
        except (ExpiredSignatureError, ValueError):
            raise ValueError("만료된 토큰입니다.")

    def check_access_token(self, access_token: Optional[str] = None):
        """
        access token의 유효성을 검사하고 상태와 provider_id를 반환합니다.
        """
        try:
            provider, provider_id = self.decode(access_token=access_token)
            return Status.SUCCESS, provider_id
        except InvalidTokenError:
            return Status.INVALID_TOKEN, None
        except ValueError:
            return Status.ACCESS_EXPIRED_TOKEN, None
        
    async def check_refresh_token(self, refresh_token: Optional[str] = None):
        """
        refresh token의 유효성을 검사하고 새 access token과 provider_id를 반환합니다.
        """
        try:
            provider, provider_id = self.decode(refresh_token=refresh_token)
            saved_refresh_token = await CacheUserRepository.get_refresh_token(provider, provider_id)

            if not saved_refresh_token or saved_refresh_token != refresh_token:
                return Status.INVALID_TOKEN, None, None

            access_token = self.get_access_token(provider, provider_id)
            return Status.SUCCESS, access_token, provider_id
        
        except InvalidTokenError:
            return Status.INVALID_TOKEN, None, None
        except ValueError:
            return Status.REFRESH_EXPIRED_TOKEN, None, None