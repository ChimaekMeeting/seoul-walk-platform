"""
frontend/streamlit_prototype/sections/header.py

현재 위치 기반 날씨·대기질 데이터를 조회하고 배너 캐러셀을 렌더링하는 헤더 섹션
"""

import time

from frontend.streamlit_prototype.bootstrap import AppContext
from frontend.streamlit_prototype.providers.base import EnvData


def render_header(ctx: AppContext) -> tuple[float, float, EnvData]:
    """
    input : ctx (AppContext)
    output: tuple[lat: float, lng: float, env: EnvData]

    AppContext에서 현재 위치 좌표를 읽고 EnvProvider로 날씨·대기질 데이터를 fetch
    배너 캐러셀을 렌더링한 후 좌표와 EnvData를 반환
    """
    t = time.time()
    lat, lng = ctx.walk_route_map.get_location()
    env      = ctx.provider.fetch(lat, lng)
    banners  = ctx.provider.get_banners(env, lat=lat, lon=lng)
    ctx.banner_carousel.render(banners)
    print(f"weather+banner: {time.time()-t:.2f}s")
    return lat, lng, env
