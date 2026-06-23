from enum import Enum
from pydantic import BaseModel

class Status(str, Enum):
    SUCCESS = "success"
    ACCESS_EXPIRED_TOKEN = "access_expired_token"
    REFRESH_EXPIRED_TOKEN = "refresh_expired_token"
    INVALID_TOKEN = "invalid_token"

class AuthResponse(BaseModel):
    status: Status