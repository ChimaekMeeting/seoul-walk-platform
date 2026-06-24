from enum import Enum
from typing import Optional

from pydantic import BaseModel


class BannerStatus(str, Enum):
    SUCCESS  = "success"
    DB_ERROR = "db_error"


class BannerItem(BaseModel):
    emoji:    str
    text:     str
    sub:      str
    key:      Optional[str]  = None
    scoring:  Optional[dict] = None
    is_event: Optional[bool] = None
    date:     Optional[str]  = None
    location: Optional[str]  = None
    url:      Optional[str]  = None


class BannerResponse(BaseModel):
    status: BannerStatus
    items:  list[BannerItem]
