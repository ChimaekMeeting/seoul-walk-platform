"""API 오류 응답과 민감정보를 남기지 않는 최소 진단 로그 계약."""

from src.config.logging import log_unexpected_error


SAFE_INTERNAL_ERROR_DETAIL = "서버 내부 오류가 발생했습니다."

__all__ = ["SAFE_INTERNAL_ERROR_DETAIL", "log_unexpected_error"]
