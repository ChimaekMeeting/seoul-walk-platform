import streamlit as st
from streamlit.components.v1 import html as st_html
from streamlit_modal import Modal


class BannerCarousel:

    def _build_html(self, banners: list) -> str:
        """
        배너 목록을 받아 캐러셀 HTML/CSS/JS 문자열을 생성하여 반환합니다.
        """
        banner_items = ""
        dots = ""
        for i, b in enumerate(banners):
            active_class = "active" if i == 0 else ""
            banner_items += f"""
    <div class="banner-item {active_class}">
        <div class="banner-label">오늘의 추천 산책</div>
        <div class="banner-text">{b['emoji']} {b['text']}</div>
        <div class="banner-sub">{b['sub']}</div>
    </div>
            """
            dots += f'<div class="dot {"active" if i == 0 else ""}" onclick="goTo({i})"></div>'

        return f"""
<div style="width:100%; margin-bottom: 20px;">
    <div class="carousel-wrap">
        <div class="carousel">{banner_items}</div>
        <div class="dots">{dots}</div>
    </div>
</div>
<style>
    .carousel-wrap {{
        background: linear-gradient(135deg, #e8f5e9 0%, #e3f2fd 100%);
        border-radius: 16px; border: 1px solid #c8e6c9;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
        padding: 20px 24px 14px; position: relative; overflow: hidden;
    }}
    .carousel {{ position: relative; min-height: 80px; }}
    .banner-item {{ display: none; animation: fadeIn 0.5s ease; }}
    .banner-item.active {{ display: block; }}
    @keyframes fadeIn {{
        from {{ opacity: 0; transform: translateY(6px); }}
        to   {{ opacity: 1; transform: translateY(0); }}
    }}
    .banner-label {{ font-size: 12px; color: #888; margin-bottom: 6px; }}
    .banner-text  {{ font-size: 20px; font-weight: 700; color: #1b5e20; margin-bottom: 4px; }}
    .banner-sub   {{ font-size: 14px; color: #555; }}
    .dots {{ display: flex; justify-content: center; gap: 6px; margin-top: 14px; }}
    .dot {{
        width: 7px; height: 7px; border-radius: 50%;
        background: #c8e6c9; cursor: pointer; transition: background 0.3s;
    }}
    .dot.active {{ background: #2e7d32; }}
</style>
<script>
    const items = document.querySelectorAll('.banner-item');
    const dots  = document.querySelectorAll('.dot');
    let current = 0, timer;
    function goTo(index) {{
        items[current].classList.remove('active'); dots[current].classList.remove('active');
        current = index;
        items[current].classList.add('active'); dots[current].classList.add('active');
        resetTimer();
    }}
    function next() {{ goTo((current + 1) % items.length); }}
    function resetTimer() {{ clearInterval(timer); timer = setInterval(next, 3500); }}
    resetTimer();
</script>
"""

    def render(self, banners: list):
        """
        배너 캐러셀 HTML, 선택 버튼, 모달 팝업을 렌더링합니다.
        """
        if not banners:
            return
        st_html(self._build_html(banners), height=160)

        modal = Modal(key="banner_modal", title="")

        if "selected_banner" not in st.session_state:
            st.session_state.selected_banner = None

        cols = st.columns(len(banners))
        for i, (col, banner) in enumerate(zip(cols, banners)):
            with col:
                if st.button(f"{banner['emoji']}", key=f"banner_btn_{i}"):
                    st.session_state.selected_banner = banner
                    modal.open()

        if modal.is_open():
            with modal.container():
                b = st.session_state.selected_banner
                if b:
                    st.markdown(f"### {b['emoji']} {b['text']}")
                    st.markdown(f"{b['sub']}")
                    st.divider()
                    if b.get("is_event"):
                        st.markdown(f"📅 **날짜:** {b['date']}")
                        st.markdown(f"📍 **장소:** {b['location']}")
                        if b.get("url"):
                            st.link_button("상세 정보 보기", b["url"])
                        if st.button("🏃 마라톤 코스 체험하기"):
                            modal.close()
                    else:
                        if st.button("🗺️ 코스 추천받기"):
                            modal.close()
