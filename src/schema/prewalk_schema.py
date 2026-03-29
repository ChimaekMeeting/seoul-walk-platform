from pydantic import BaseModel
from typing import Optional

class InitRequest(BaseModel):
    user_uuid: str
    lat: float
    lon: float

class ChatRequest(BaseModel):
    thread_id: str
    user_prompt: str

class ChatResponse(BaseModel):
    thread_id: str
    message: str

class UserPreferenceContext(BaseModel):
    is_circular: Optional[bool]
    origin: Optional[str]
    destination: Optional[str]
    purpose: Optional[str]