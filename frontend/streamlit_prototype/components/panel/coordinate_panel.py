import streamlit as st


class CoordinatePanel:

    def render(self):
        """
        출발지·도착지 좌표를 표시하고 각 초기화 버튼을 렌더링합니다.
        """
        st.divider()
        c1, c2 = st.columns(2)
        with c1:
            if st.session_state.start:
                st.success(f"🟢 출발지\n\n`{st.session_state.start[0]:.5f}, {st.session_state.start[1]:.5f}`")
                if st.button("출발지 초기화"):
                    st.session_state.start = None
                    st.rerun()
            else:
                st.warning("출발지를 설정해주세요")
        with c2:
            if st.session_state.end:
                st.error(f"🔴 도착지\n\n`{st.session_state.end[0]:.5f}, {st.session_state.end[1]:.5f}`")
                if st.button("도착지 초기화"):
                    st.session_state.end = None
                    st.rerun()
            else:
                st.warning("도착지를 설정해주세요")
