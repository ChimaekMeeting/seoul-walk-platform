from sqlalchemy import Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.sql import func
from src.db.connection import Base

class Route(Base):
    __tablename__ = "routes"
    id         = Column(Integer, primary_key=True, index=True)
    name       = Column(String, nullable=False)
    distance   = Column(Float)
    geojson    = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())

class UserQuery(Base):
    __tablename__ = "user_queries"
    id         = Column(Integer, primary_key=True, index=True)
    raw_text   = Column(String)
    parsed     = Column(JSON)
    created_at = Column(DateTime, server_default=func.now())
