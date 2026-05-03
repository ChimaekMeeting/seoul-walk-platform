import streamlit as st
import asyncio
from api_tester import UserAPITester, WeatherAPITester, PrewalkAPITester

# API 클라이언트 초기화
user_api = UserAPITester()
weather_api = WeatherAPITester()
prewalk_api = PrewalkAPITester()

async def init_session():
    """사용자 UUID 생성 및 서버 세션 초기화"""
    if "user_uuid" not in st.session_state:
        # 1. 유저 생성
        user_res = await user_api.post_user()
        st.session_state.user_uuid = user_res.get("user_uuid")
        
        # 2. 위치 정보 가져오기 (기본값: 화정역)
        lat = 37.634496
        lon = 126.832852
        
        # 3. Prewalk 세션 초기화 (서버의 대화 state 생성)
        init_res = await prewalk_api.post_init(
            user_uuid=st.session_state.user_uuid, 
            lat=lat, 
            lon=lon
        )
        st.session_state.thread_id = init_res.get("thread_id")
        st.session_state.state = init_res.get("state")

        st.session_state.messages = []
        first_message = init_res.get("message")
        st.session_state.messages.append({"role": "assistant", "content": first_message})
        
        st.session_state.initialized = True

async def main():
    st.set_page_config(page_title="산책 메이트 챗봇", page_icon="🤖")
    st.title("🤖 AI 산책 메이트")
    st.caption("당신에게 딱 맞는 산책 경로를 설계해 드립니다.")

    # 세션 초기화 실행
    if "initialized" not in st.session_state:
        with st.spinner("세션을 연결 중입니다..."):
            await init_session()
            st.rerun()

    # 대화 기록 표시
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # 챗봇 입력창
    if prompt := st.chat_input("챗봇과 자유롭게 대화를 나눠보세요!"):
        # 유저 메시지 표시 및 저장
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 챗봇 응답 생성
        with st.chat_message("assistant"):
            with st.spinner("생각 중..."):
                # 1. 의도 파악 및 대화 진행 API 호출
                response = await prewalk_api.post_intent(
                    thread_id=st.session_state.thread_id, 
                    user_prompt=prompt
                )
                
                answer = response.get("message", "죄송합니다. 응답을 이해하지 못했습니다.")
                state = response.get("state")
                next_node = state.get("next_node")

                st.markdown(answer)
                st.session_state.messages.append({"role": "assistant", "content": answer})

                # 2. 만약 대화가 완료되었다면(next_node == 'end') 가중치 정보 가져오기
                if next_node == "end":
                    weights_res = await prewalk_api.get_weights(st.session_state.thread_id)
                    st.success("📍 산책 정보 수집 완료! 경로 생성을 시작합니다.")
                    st.json(weights_res) # 가중치 결과 확인용

if __name__ == "__main__":
    asyncio.run(main())