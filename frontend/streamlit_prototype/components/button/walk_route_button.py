import asyncio

import httpx
import streamlit as st

from frontend.streamlit_prototype.api.walk_router import WalkRouter
from frontend.streamlit_prototype.api.auth_client import call_with_auto_refresh
from frontend.streamlit_prototype.schema.walk_schema import (
    Coordinate, WalkRouteRequest, WalkRouteResponse,
)


class WalkRouteButton:

    def _call_api(self, request: WalkRouteRequest) -> WalkRouteResponse | None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            raw = loop.run_until_complete(
                call_with_auto_refresh(
                    lambda token: WalkRouter().post_route(token, request.model_dump())
                )
            )
            if "detail" in raw and "status" not in raw:
                return WalkRouteResponse(
                    status="FAILED", mode=request.mode, coordinates=[], total_km=0.0,
                    fallback_reason=raw["detail"],
                )
            return WalkRouteResponse(**raw)
        except httpx.HTTPStatusError as e:
            detail = e.response.json().get("detail", "알 수 없는 오류가 발생했습니다.")
            st.error(detail)
            return None

    def _build_request(self, mode: str, target_km: float) -> WalkRouteRequest:
        return WalkRouteRequest(
            mode       = mode,
            target_km  = target_km,
            origin     = Coordinate(
                lat = st.session_state.start[0],
                lon = st.session_state.start[1],
            ),
            destination = (
                Coordinate(lat=st.session_state.end[0], lon=st.session_state.end[1])
                if st.session_state.end else None
            ),
        )

    def _save(self, response: WalkRouteResponse) -> None:
        st.session_state.route_coordinates = response.coordinates
        st.session_state.route_distance    = response.total_km
        st.session_state.route_result      = response.model_dump()

    def render(
        self,
        input_mode: str,
        selected_mode: str,
        target_km: float,
        lat: float,
        lng: float,
    ) -> None:
        """경로 추천 버튼을 렌더링하고, 클릭 또는 AI 챗봇 완료 시 경로를 계산합니다."""
        if input_mode == "직접 설정" and st.session_state.start:
            st.divider()
            if st.button("🚶 경로 추천받기", type="primary", use_container_width=True):
                if selected_mode.startswith("oneway_") and not st.session_state.end:
                    st.error("편도 모드에서는 도착지를 설정해야 합니다!")
                else:
                    with st.spinner("최적의 경로를 계산하는 중..."):
                        req      = self._build_request(selected_mode, target_km)
                        response = self._call_api(req)
                    if response is None:
                        pass
                    elif response.status == "FAILED":
                        st.error(f"경로 생성 실패: {response.fallback_reason}")
                    else:
                        self._save(response)
                        st.rerun()

        elif input_mode == "AI 챗봇":
            state = st.session_state.get("state", {})
            if state and state.get("next_node") == "end" and not st.session_state.route_coordinates:
                user_context = state.get("user_context", {})
                origin       = user_context.get("origin", {})
                destination  = user_context.get("destination")

                with st.spinner("최적의 경로를 계산하는 중..."):
                    req = WalkRouteRequest(
                        mode      = selected_mode,
                        target_km = target_km,
                        origin    = Coordinate(
                            lat = origin.get("lat", lat),
                            lon = origin.get("lon", lng),
                        ),
                        destination = (
                            Coordinate(lat=destination.get("lat"), lon=destination.get("lon"))
                            if destination else None
                        ),
                    )
                    response = self._call_api(req)
                    if response is None:
                        pass
                    elif response.status == "FAILED":
                        st.error(f"경로 생성 실패: {response.fallback_reason}")
                    else:
                        self._save(response)
                        st.rerun()
