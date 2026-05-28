"""
?곕떇/?ㅼ씠?댄듃 ?몃룄 寃쎈줈 異붿쿇 紐⑤뱢.

DB?먯꽌 river쨌park쨌bike_track 肄붿뒪瑜?議고쉶????
?ъ슜??異쒕컻????紐⑹쟻吏 援ш컙??Edge Penalty + ?쒕뜡 寃쎌쑀吏(path_oneway_random)濡??앹꽦?⑸땲??

?몄텧 ???꾩닔 議곌굔
-----------------
- G??媛??ｌ???``custom_score`` ?띿꽦???명똿?섏뼱 ?덉뼱???⑸땲??
  (_apply_running_weights() 瑜?癒쇱? ?몄텧?섏꽭??)

?몃? ?섏〈??
-----------
- src.service.route.path_oneway_random.oneway_random_route
- src.repository.layer.running_repository.RunningRepository.get_running_layer_near
"""

import networkx as nx

from src.route_engine.path_oneway_random import oneway_random_route
from src.route_engine.path_utils import find_nearest_node
from src.repository.layer.running_repository import RunningRepository

RUNNING_COURSE_TYPES = ["river", "park", "bike_track"]


def oneway_running_route(
    G: nx.Graph,
    start_lat: float,
    start_lon: float,
    dest_lat: float,
    dest_lon: float,
    target_m: float,
    radius_m: float,
    session,
) -> dict:
    """
    ?곕떇/?ㅼ씠?댄듃 ?몃룄 寃쎈줈瑜??앹꽦?⑸땲??

    諛섍꼍 ??river쨌park쨌bike_track 肄붿뒪瑜?DB?먯꽌 議고쉶?섏뿬 ``matched_courses``濡?諛섑솚?섍퀬,
    ?ъ슜??異쒕컻????紐⑹쟻吏 援ш컙??Edge Penalty + ?쒕뜡 寃쎌쑀吏 ?뚭퀬由ъ쬁?쇰줈 ?앹꽦?⑸땲??
    ??긽 ?고쉶 寃쎈줈瑜??ъ슜?섎ŉ 理쒕떒 寃쎈줈(Dijkstra) 遺꾧린???놁뒿?덈떎.

    .. note::
        ``G``??媛??ｌ???``custom_score``媛 ?놁쑝硫?寃쎈줈 ?덉쭏??蹂댁옣?섏? ?딆뒿?덈떎.
        ?몄텧 ?꾩뿉 ``_apply_running_weights(G)``瑜?癒쇱? ?ㅽ뻾?섏꽭??

        ``session`` ?뚮씪誘명꽣???명꽣?섏씠???쇨??깆쓣 ?꾪빐 議댁옱?섎ŉ,
        ?ㅼ젣 DB ?곌껐? ``get_running_layer_near()`` ?대??먯꽌 ?먯껜 愿由ы빀?덈떎.

    Args:
        G         (nx.Graph)  : ``custom_score``媛 ?명똿??NetworkX 洹몃옒??
        start_lat (float)     : ?ъ슜??異쒕컻 ?꾨룄.
        start_lon (float)     : ?ъ슜??異쒕컻 寃쎈룄.
        dest_lat  (float)     : 紐⑹쟻吏 ?꾨룄.
        dest_lon  (float)     : 紐⑹쟻吏 寃쎈룄.
        target_m  (float)     : 紐⑺몴 嫄곕━ (誘명꽣). 寃쎌쑀吏 ?꾩튂 怨꾩궛???ъ슜?⑸땲??
        radius_m  (float)     : DB 肄붿뒪 寃??諛섍꼍 (誘명꽣).
        session               : 誘몄궗?? ?쒕챸 ?듭씪 紐⑹쟻?쇰줈留?議댁옱.

    Returns:
        dict: ?꾨옒 ?ㅻ? ?ы븿?섎뒗 ?뺤뀛?덈━.

        - ``mode``              (str)        : ``"oneway_running"``
        - ``coordinates``       (list)       : ``[[lat, lon], ...]`` ?뺥깭??寃쎈줈 醫뚰몴 紐⑸줉.
        - ``total_distance_km`` (float)      : ?앹꽦??寃쎈줈??珥?嫄곕━ (km).
        - ``matched_courses``   (list[dict]) : 諛섍꼍 ??議고쉶??肄붿뒪 紐⑸줉.
          肄붿뒪媛 ?놁쑝硫?鍮?由ъ뒪?? 媛???ぉ? ``get_running_layer_near()`` 諛섑솚 ?뺤떇怨??숈씪.
    """
    courses = RunningRepository.get_running_layer_near(
        lat=start_lat,
        lon=start_lon,
        radius_m=radius_m,
        is_circular=False,
        course_types=RUNNING_COURSE_TYPES,
    )

    end_node = find_nearest_node(G, dest_lat, dest_lon)

    # 留ㅼ묶 肄붿뒪 ?놁쑝硫??ъ슜???꾩튂?먯꽌 ?대갚
    if not courses:
        start_node = find_nearest_node(G, start_lat, start_lon)
        result = oneway_random_route(G, start_node, end_node, target_m / 1000, weight="custom_score")
        result["mode"] = "oneway_running"
        result["matched_courses"] = []
        return result

    # get_running_layer_near??distance_from_origin_m ?ㅻ쫫李⑥닚 ?뺣젹 ??媛??媛源뚯슫 肄붿뒪 ?ъ슜
    best_course = courses[0]
    start_node = find_nearest_node(G, best_course["start_lat"], best_course["start_lon"])

    result = oneway_random_route(G, start_node, end_node, target_m / 1000, weight="custom_score")
    result["mode"] = "oneway_running"
    result["matched_courses"] = courses
    return result



