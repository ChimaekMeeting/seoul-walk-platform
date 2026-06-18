from datetime import datetime
from typing import Optional

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.entity.base import Base


class CsvRaw(Base):
    __tablename__ = "csv_raw"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    query_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    geom = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    properties: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
