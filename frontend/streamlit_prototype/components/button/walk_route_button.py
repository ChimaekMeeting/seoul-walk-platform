import asyncio

import streamlit as st

from frontend.streamlit_prototype.api.walk_router import WalkRouter
from frontend.streamlit_prototype.schema.walk_schema import (
    Coordinate, WalkRouteRequest, WalkRouteResponse,
)


class WalkRouteButton:

    def _call_api(self, request: WalkRouteRequest) -> WalkRouteResponse:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        raw = loop.run_until_complete(WalkRouter().post_route(request.model_dump()))
        return WalkRouteResponse(**raw)

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
                    req = self._build_request(selected_mode, target_km)
                    try:
                        with st.spinner("최적의 경로를 계산하는 중..."):
                            response = self._call_api(req)
                    except Exception as e:
                        st.error(f"백엔드 통신 오류 발생: 경로를 생성할 수 없습니다. 다시 시도해 주세요. 상세: {e}")
                        return

                    if response.status == "FAILED":
                        st.error(f"경로 생성 실패: {response.fallback_reason}")
                    else:
                        self._save(response)
                        st.rerun()

        elif input_mode == "AI 챗봇":
            state = st.session_state.get("state", {})
            if state and state.get("is_complete") and not st.session_state.route_coordinates:
                # 1) 백엔드에서 이미 route_result를 내려준 경우 -> 재호출 없이 즉시 렌더링
                route_res = state.get("route_result")
                if route_res:
                    response = WalkRouteResponse(**route_res)
                    if response.status == "FAILED":
                        st.error(f"경로 생성 실패: {response.fallback_reason}")
                    else:
                        self._save(response)
                        st.rerun()
                    return

                # 2) 예외/이전 흐름: 백엔드 경로가 없으면 기존 fallback API 호출
                user_context = state.get("user_context", {})
                origin       = user_context.get("origin", {})
                destination  = user_context.get("destination")

                with st.spinner("최적의 경로를 계산하는 중..."):
                    req = WalkRouteRequest(
                        mode      = selected_mode,
                        target_km = target_km,
                        origin    = Coordinate(
                            lat = origin.get("lat") or lat,
                            lon = origin.get("lon") or lng,
                        ),
                        destination = (
                            Coordinate(lat=destination.get("lat"), lon=destination.get("lon"))
                            if (
                                destination
                                and destination.get("lat") is not None
                                and destination.get("lon") is not None
                            )
                            else None
                        ),
                        user_context = user_context,
                        current_location = Coordinate(lat=lat, lon=lng)
                    )
                    
                    try:
                        response = self._call_api(req)
                        if response.status == "FAILED":
                            st.error(f"경로 생성 실패: {response.fallback_reason}")
                        else:
                            self._save(response)
                            st.rerun()
                    except Exception as e:
                        st.error(f"백엔드 통신 오류 발생: 경로를 생성할 수 없습니다. 다시 시도해 주세요. 상세: {e}")
