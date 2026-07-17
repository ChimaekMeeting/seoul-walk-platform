from pydantic import BaseModel

from src.interfaces.schema.user_schema import UserResponse

class LoginUrlResponse(BaseModel):
    url: str

class LoginResponse(UserResponse):
    token_type: str = "Bearer"
    access_token: str
    refresh_token: str

class MobileLoginRequest(BaseModel):
    access_token: str