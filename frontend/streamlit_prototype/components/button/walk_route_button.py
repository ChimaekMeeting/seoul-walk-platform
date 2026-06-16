import streamlit as st

from src.service.route.route_service import RouteService
from src.route_engine.engines.child_walk_route import ChildWalkRoute
from frontend.streamlit_prototype.schema.prewalk_schema import Weights


class WalkRouteButton:

    def __init__(self, G):
        self.G = G
        self._route_service = RouteService()

    def _build_context(
        self, selected_mode: str, distance_km: float, lat: float, lng: float
    ) -> dict:
        """
        경로 계산 API에 전달할 context 딕셔너리를 생성합니다.
        """
        return {
            "mode": selected_mode,
            "distance_km": distance_km,
            "origin": {
                "place_name": "", "address": "",
                "coordinate": {"lat": st.session_state.start[0], "lon": st.session_state.start[1]},
            },
            "destination": (
                {"place_name": "", "address": "",
                 "coordinate": {"lat": st.session_state.end[0], "lon": st.session_state.end[1]}}
                if st.session_state.end else None
            ),
            "purpose": "산책",
        }

    def _save(self, result: dict) -> None:
        """
        경로 계산 결과를 세션 상태에 저장합니다.
        """
        st.session_state.route_coordinates = result["coordinates"]
        st.session_state.route_distance    = result["total_distance_km"]
        st.session_state.route_result      = result

    def render(
        self,
        input_mode: str,
        selected_mode: str,
        distance_km: float,
        child_friendly: bool,
        safety_w: float,
        nature_w: float,
        lat: float,
        lng: float,
    ) -> None:
        """
        경로 추천 버튼을 렌더링하고, 클릭 또는 AI 챗봇 완료 시 경로를 계산합니다.
        """
        weights = Weights(safety=safety_w, nature=nature_w)

        if input_mode == "직접 설정" and st.session_state.start:
            st.divider()
            if st.button("🚶 경로 추천받기", type="primary", use_container_width=True):
                if selected_mode in ["oneway_shortest", "oneway_random"] and not st.session_state.end:
                    st.error("편도 모드에서는 도착지를 설정해야 합니다!")
                else:
                    with st.spinner("최적의 경로를 계산하는 중..."):
                        context = self._build_context(selected_mode, distance_km, lat, lng)
                        result = (
                            ChildWalkRoute().get_route(context, weights, self.G)
                            if child_friendly
                            else self._route_service.get_route(context, weights, self.G)
                        )
                        if "error" in result:
                            st.error(f"오류 발생: {result['error']}")
                        else:
                            self._save(result)
                            st.rerun()

        elif input_mode == "AI 챗봇":
            state = st.session_state.get("state", {})
            if state and state.get("next_node") == "end" and not st.session_state.route_coordinates:
                user_context = state.get("user_context", {})
                origin      = user_context.get("origin", {})
                destination = user_context.get("destination")
                with st.spinner("최적의 경로를 계산하는 중..."):
                    context = {
                        "mode": selected_mode, "distance_km": distance_km,
                        "origin": {
                            "place_name": origin.get("place_name", ""), "address": origin.get("address", ""),
                            "coordinate": {"lat": origin.get("lat", lat), "lon": origin.get("lon", lng)},
                        },
                        "destination": (
                            {"place_name": destination.get("place_name", ""), "address": destination.get("address", ""),
                             "coordinate": {"lat": destination.get("lat"), "lon": destination.get("lon")}}
                            if destination else None
                        ),
                        "purpose": user_context.get("purpose", "산책"),
                    }
                    result = self._route_service.get_route(context, weights, self.G)
                    if "error" in result:
                        st.error(f"오류 발생: {result['error']}")
                    else:
                        self._save(result)
                        st.rerun()
