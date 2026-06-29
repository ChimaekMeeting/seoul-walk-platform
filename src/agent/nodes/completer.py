import logging
from typing import Optional

from src.schema.prewalk_schema import (
    State,
    Location,
    CircularPreference,
    OnewayPreference,
    OnewayShortestPreference,
)

logger = logging.getLogger(__name__)


class Completer:
    """
    필수 정보가 모두 모인 뒤, 사용자에게 보낼 확인 질문을 생성하고
    확인 대기(awaiting_confirmation) 상태로 전환하는 노드.
    """

    async def run(self, state: State) -> State:
        state.response              = self._build_confirmation_message(state)
        state.awaiting_confirmation = True
        state.is_complete           = False
        logger.info(f"확인 대기 상태로 전환합니다: {state.response}")
        return state

    def _build_confirmation_message(self, state: State) -> str:
        """
        경로 실행 전 사용자에게 보낼 확인 질문을 생성합니다.
        """
        ctx     = state.user_context
        current = state.current_location

        if isinstance(ctx, (OnewayShortestPreference, OnewayPreference)):
            origin    = ctx.origin
            dest      = ctx.destination
            dest_name = dest.place_name if dest and dest.place_name else "목적지"

            if self._is_same_location(origin, current):
                return f"현재 위치부터 {dest_name}까지가 맞나요?"
            origin_name = origin.place_name if origin and origin.place_name else "현재 위치"
            return f"{origin_name}부터 {dest_name}까지가 맞나요?"

        if isinstance(ctx, CircularPreference):
            origin    = ctx.origin
            target_km = ctx.target_km or 3.0
            km_str    = str(int(target_km)) if target_km == int(target_km) else str(target_km)

            if self._is_same_location(origin, current):
                return f"현재 위치에서 출발하는 {km_str}km 순환 산책이 맞나요?"
            origin_name = origin.place_name if origin and origin.place_name else "현재 위치"
            return f"{origin_name}에서 출발하는 {km_str}km 순환 산책이 맞나요?"

        return "이 경로로 진행할까요?"

    @staticmethod
    def _is_same_location(a: Optional[Location], b: Optional[Location]) -> bool:
        """
        두 Location이 같은 지점인지 좌표 기준으로 비교합니다.
        """
        if a is None or b is None:
            return False
        if (a.lat is not None and b.lat is not None
                and a.lon is not None and b.lon is not None):
            return abs(a.lat - b.lat) < 1e-6 and abs(a.lon - b.lon) < 1e-6
        return False
