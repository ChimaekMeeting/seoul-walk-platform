import logging
import sys


def log_unexpected_error(
    logger: logging.Logger, event: str, error: Exception
) -> None:
    """요청값·예외 메시지·traceback 없이 사건명과 예외 형식만 기록합니다."""
    logger.error("%s | error_type=%s", event, type(error).__name__)


def setup_logging() -> None:
    fmt = "[%(levelname)s] [%(name)s] %(message)s"
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
