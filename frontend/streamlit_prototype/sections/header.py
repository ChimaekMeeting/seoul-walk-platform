import time

from frontend.streamlit_prototype.bootstrap import AppContext
from frontend.streamlit_prototype.providers.base import EnvData


def render_header(ctx: AppContext) -> tuple[float, float, EnvData]:
    t = time.time()
    lat, lng = ctx.walk_route_map.get_location()
    env      = ctx.provider.fetch(lat, lng)
    banners  = ctx.provider.get_banners(env)
    ctx.banner_carousel.render(banners)
    print(f"weather+banner: {time.time()-t:.2f}s")
    return lat, lng, env
