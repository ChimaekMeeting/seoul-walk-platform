import asyncio

import streamlit as st

from frontend.streamlit_prototype.api.user_router import UserRouter
from frontend.streamlit_prototype.api.prewalk_router import PrewalkRouter
from frontend.streamlit_prototype.schema.prewalk_schema import InitRequest, ChatRequest


class ChatPanel:

    def __init__(self):
        self.user_router = UserRouter()
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
        사용자 UUID를 생성하고 산책 인터뷰 서버 세션을 초기화합니다.
        """
        if "user_uuid" not in st.session_state:
            user_res = await self.user_router.post_user()
            st.session_state.user_uuid = user_res.get("user_uuid")

            init_req = InitRequest(
                user_uuid=st.session_state.user_uuid,
                lat=37.634496,
                lon=126.832852,
            )
            init_res = await self.prewalk_router.post_init(
                user_uuid=init_req.user_uuid,
                lat=init_req.lat,
                lon=init_req.lon,
            )
            st.session_state.thread_id = init_res.get("thread_id")
            st.session_state.state = init_res.get("state")
            st.session_state.messages = []
            st.session_state.messages.append({"role": "assistant", "content": init_res.get("state", {}).get("response")})
            st.session_state.initialized = True

    async def chat_and_assign_weights(self, prompt: str):
        """
        LLM과의 상호작용을 통해 산책 경로 가중치를 결정합니다.
        """
        chat_req = ChatRequest(thread_id=st.session_state.thread_id, user_prompt=prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        response = await self.prewalk_router.post_intent(
            thread_id=chat_req.thread_id,
            user_prompt=chat_req.user_prompt,
        )

        answer = response.get("state", {}).get("response", "죄송합니다. 응답을 이해하지 못했습니다.")
        state  = response.get("state")

        st.session_state.messages.append({"role": "assistant", "content": answer})
        st.session_state.state = state

        if state.get("next_node") == "end":
            st.session_state.weights = await self.prewalk_router.get_weights(st.session_state.thread_id)

    def render(
        self,
        selected_mode: str,
        target_km: float,
    ) -> tuple[str, float] | None:
        """
        AI 챗봇 패널을 렌더링하고, 대화 완료 시 업데이트된 (mode_key, target_km)를 반환합니다.
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

        state = st.session_state.get("state", {})
        if state and state.get("next_node") == "end":
            st.success("📍 산책 정보 수집 완료! 아래 지도에서 출발지를 확인하고 경로를 추천받으세요.")
            weights_data = st.session_state.get("weights", {})
            with st.expander("챗봇 반환 JSON 확인"):
                st.json({"state": state, "weights": weights_data})
            user_context = state.get("user_context", {})
            if user_context:
                mode_map = {
                    "Circular":    "circular_random",
                    "Destination": "oneway_shortest",
                    "Distance":    "circular_random",
                }
                return (
                    mode_map.get(user_context.get("mode", "Circular"), selected_mode),
                    user_context.get("distance_km", target_km),
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

        if "state" in st.session_state and st.session_state.state:
            state = st.session_state.state
            if state.get("next_node") == "end":
                st.success("📍 산책 정보 수집 완료! 경로 생성을 시작합니다.")
                st.json(st.session_state.weights)
                st.json(st.session_state.state)


