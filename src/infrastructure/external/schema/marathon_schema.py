from datetime import date
from pydantic import BaseModel


class MarathonEvent(BaseModel):
    """
    마라톤 대회 일정의 개별 항목을 나타냅니다.
    """
    name: str
    date: date
    location: str
    slug: str
