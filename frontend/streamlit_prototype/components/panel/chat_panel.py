import asyncio

import folium
import streamlit as st
from streamlit_folium import st_folium

from frontend.streamlit_prototype.api.prewalk_router import PrewalkRouter
from frontend.streamlit_prototype.schema.prewalk_schema import InitRequest, ChatRequest


class ChatPanel:

    def __init__(self):
        self.prewalk_router = PrewalkRouter()

    def run_async(self, coro):
        """
        비동기 코루틴을 동기 컨텍스트에서 실행합니다.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

    async def init_session(self):
        """
        access_token으로 산책 인터뷰 서버 세션을 초기화합니다.
        """
        if "initialized" not in st.session_state:
            access_token = st.session_state.get("access_token")

            init_req = InitRequest(
                lat=37.634496,
                lon=126.832852,
            )
            init_res = await self.prewalk_router.post_init(
                access_token=access_token,
                lat=init_req.lat,
                lon=init_req.lon,
            )

            if init_res.get("status") != "success":
                st.error("세션 초기화에 실패했습니다. 다시 로그인해주세요.")
                return

            st.session_state.thread_id    = init_res.get("thread_id")
            st.session_state.state        = init_res.get("state")
            st.session_state.route_result = None
            st.session_state.messages     = []
            st.session_state.messages.append({"role": "assistant", "content": init_res.get("state", {}).get("response")})
            st.session_state.initialized  = True

    async def chat_and_assign_weights(self, prompt: str):
        """
        LLM과의 상호작용을 통해 산책 정보를 수집하고, 완료 시 경로를 생성합니다.
        """
        access_token = st.session_state.get("access_token")
        chat_req = ChatRequest(thread_id=st.session_state.thread_id, user_prompt=prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        response = await self.prewalk_router.post_intent(
            access_token=access_token,
            thread_id=chat_req.thread_id,
            user_prompt=chat_req.user_prompt,
        )

        if response.get("status") != "success":
            st.session_state.messages.append({
                "role": "assistant",
                "content": "세션이 만료되었거나 접근 권한이 없습니다. 다시 로그인해주세요.",
            })
            return

        state  = response.get("state", {})
        answer = state.get("response", "죄송합니다. 응답을 이해하지 못했습니다.")

        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.state = state

        route_result = state.get("route_result")
        if route_result:
            st.session_state.route_result = route_result

    def _render_route_map(self, route_result: dict) -> None:
        """
        route_result의 coordinates를 Folium 지도에 폴리라인으로 렌더링합니다.
        """
        coords = route_result.get("coordinates", [])
        if not coords:
            return

        st.divider()
        st.success(f"✅ 경로 생성 완료! ({route_result.get('mode', '')})")
        st.markdown("### 🗺️ 산책 경로")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("총 거리", f"{route_result.get('total_km', 0):.2f} km")
        with col2:
            time_min = round(route_result.get("total_km", 0) / 4.0 * 60)
            st.metric("예상 소요 시간", f"{time_min} 분")

        m = folium.Map(location=coords[0], zoom_start=15, tiles="cartodbpositron")

        folium.Marker(
            coords[0], popup="출발지", tooltip="출발지",
            icon=folium.Icon(color="green", icon="play", prefix="fa"),
        ).add_to(m)

        if len(coords) > 1:
            folium.Marker(
                coords[-1], popup="도착지", tooltip="도착지",
                icon=folium.Icon(color="red", icon="flag", prefix="fa"),
            ).add_to(m)

        folium.PolyLine(
            locations=coords,
            color="#4A90E2", weight=6, opacity=0.8,
            tooltip=f"총 {route_result.get('total_km', 0):.2f} km",
        ).add_to(m)
        m.fit_bounds(coords)

        st_folium(m, width="100%", height=500)

    def render(
        self,
        selected_mode: str,
        target_km: float,
    ) -> tuple[str, float] | None:
        """
        AI 챗봇 패널을 렌더링하고, 경로 생성 완료 시 업데이트된 (mode_key, target_km)를 반환합니다.
        """
        st.markdown("### 🤖 AI 산책 메이트")

        if "initialized" not in st.session_state:
            with st.spinner("세션을 연결 중입니다..."):
                self.run_async(self.init_session())
                st.rerun()

        for message in st.session_state.get("messages", []):
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("챗봇과 자유롭게 대화를 나눠보세요!"):
            with st.spinner("생각 중..."):
                self.run_async(self.chat_and_assign_weights(prompt))
            st.rerun()

        if st.session_state.get("route_result"):
            self._render_route_map(st.session_state.route_result)

        state = st.session_state.get("state", {})
        if state and state.get("is_complete") and st.session_state.get("route_result"):
            user_context = state.get("user_context", {})
            if user_context:
                return (
                    user_context.get("mode", selected_mode),
                    user_context.get("target_km", target_km),
                )
        return None

    def render_page(self):
        """
        AI 산책 메이트 챗봇 독립 실행 페이지를 렌더링합니다.
        """
        st.set_page_config(page_title="산책 메이트 챗봇", page_icon="🤖")
        st.title("🤖 AI 산책 메이트")
        st.caption("당신에게 딱 맞는 산책 경로를 설계해 드립니다.")

        if "initialized" not in st.session_state:
            with st.spinner("세션을 연결 중입니다..."):
                self.run_async(self.init_session())
                st.rerun()

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("챗봇과 자유롭게 대화를 나눠보세요!"):
            with st.spinner("생각 중..."):
                self.run_async(self.chat_and_assign_weights(prompt))
            st.rerun()

        if st.session_state.get("route_result"):
            self._render_route_map(st.session_state.route_result)
