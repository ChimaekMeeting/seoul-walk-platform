from pydantic import BaseModel
from typing import Optional

from src.interfaces.schema.auth_schema import Status

class UserResponse(BaseModel):
    status: Status
    nickname: Optional[str] = None