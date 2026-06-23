from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import Integer, String, JSON
from src.entity.base import Base


class Banner(Base):
    __tablename__ = "banners"

    id:       Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key:      Mapped[str] = mapped_column(String(50),  nullable=False, unique=True)
    category: Mapped[str] = mapped_column(String(20),  nullable=False)
    emoji:    Mapped[str] = mapped_column(String(10),  nullable=False)
    text:     Mapped[str] = mapped_column(String(100), nullable=False)
    sub:      Mapped[str] = mapped_column(String(100), nullable=False)
    scoring:  Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    def to_dict(self) -> dict:
        return {
            "key":     self.key,
            "emoji":   self.emoji,
            "text":    self.text,
            "sub":     self.sub,
            "scoring": self.scoring,
        }
