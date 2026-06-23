import logging

logger = logging.getLogger(__name__)


def validate_oneway_requires_destination(mode_value: str, destination: object) -> None:
    """
    VAL-MODE-001: 편도 모드에서 도착지 누락 차단
    """
    if mode_value.startswith("oneway_") and destination is None:
        raise ValueError("편도 모드에서는 도착지(목적지) 좌표 입력이 필수입니다.")


def sanitize_circular_destination(mode_value: str, destination: object) -> object:
    """
    VAL-MODE-002: 순환 모드에서 도착지가 입력된 경우 무시(sanitize)하고 경고 로깅
    """
    if mode_value.startswith("circular_") and destination is not None:
        logger.warning(
            "순환 모드에서는 입력하신 도착지 좌표가 무시되고, "
            "출발지 중심으로 되돌아오는 코스가 생성됩니다."
        )
        return None
    return destination
