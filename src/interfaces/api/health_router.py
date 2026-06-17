"""
src/interfaces/api/health_router.py

GET /api/health 엔드포인트 정의
DB 연결 상태를 확인하고 결과를 반환
"""
from fastapi import APIRouter
from src.database.postgresql import health_check

router = APIRouter(tags=["health"])


@router.get("/api/health")
def get_health():
    """
    input : 없음
    output: {"ok": bool}

    DB 연결 상태를 확인해 ok 필드로 반환
    """
    return {"ok": health_check()}
