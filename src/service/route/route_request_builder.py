from typing import Dict, Any
from fastapi import HTTPException
from src.interfaces.schema.walk_schema import WalkRouteRequest


SUPPORTED_MODES = {
    "circular_random",
    "circular_child",
    "circular_running",
    "oneway_shortest",
    "oneway_random",
    "oneway_child",
    "oneway_running",
}


class RouteRequestBuilder:
    @staticmethod
    def build(req: WalkRouteRequest) -> Dict[str, Any]:
        user_context = req.user_context or {}

        # 1. Origin (출발지) 명시적 None 검사 및 fallback
        origin = req.origin
        if not origin or origin.lat is None or origin.lon is None:
            if req.current_location and req.current_location.lat is not None and req.current_location.lon is not None:
                origin = req.current_location
            else:
                raise HTTPException(status_code=400, detail="출발지 좌표를 확인할 수 없습니다.")

        # 2. Destination(목적지) 보정
        destination = req.destination
        requested_mode = req.mode or "circular_random"
        requested_oneway = requested_mode.startswith("oneway")
        has_destination = (
            destination is not None
            and destination.lat is not None
            and destination.lon is not None
        )

        # 3. AI 챗봇 요청에서만 profile_name을 mode 보정에 사용합니다.
        profile_name = str(user_context.get("profile_name", "default")).lower().strip()
        is_ai_request = bool(user_context)

        if is_ai_request and profile_name == "child":
            mode = "oneway_child" if requested_oneway and has_destination else "circular_child"
        elif is_ai_request and profile_name == "running":
            mode = "oneway_running" if requested_oneway and has_destination else "circular_running"
        else:
            mode = requested_mode

        if mode.startswith("oneway"):
            if not destination or destination.lat is None or destination.lon is None:
                mode = "circular_random"
                destination = None
        else:
            destination = None

        if mode not in SUPPORTED_MODES:
            mode = "circular_random"

        # 4. Distance (거리) 명시적 방어
        raw_target = req.target_km
        if raw_target is None:
            raw_target = user_context.get("target_km") or user_context.get("distance_km") or 3.0

        try:
            target_km = float(raw_target)
        except (TypeError, ValueError):
            target_km = 3.0

        return {
            "origin": origin,
            "destination": destination,
            "target_km": target_km,
            "mode": mode,
        }
