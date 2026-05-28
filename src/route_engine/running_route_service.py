"""
?곕떇/?ㅼ씠?댄듃 紐⑤뱶 寃쎈줈 異붿쿇 ?쒕퉬??

?섏쿇蹂쨌怨듭썝 ?꾩＜ 肄붿뒪瑜??쒗솚(circular) / ?몃룄(oneway) 濡??섎닠 諛섑솚?⑸땲??

二쇱슂 ?⑥닔
---------
get_circular_route(lat, lon, target_km, ...)  ??異쒕컻??湲곗? 猷⑦봽 肄붿뒪
get_oneway_route(lat, lon, end_lat, end_lon, ...) ??異쒕컻?????꾩갑???⑤갑??肄붿뒪
"""

from __future__ import annotations

import math
import time
from typing import Optional

import networkx as nx

from src.repository.layer.running_repository import RunningRepository
from src.repository.network.graph_repository import GraphRepository
from src.interfaces.schema.running_schema import (
    CircularRunningResponse,
    CourseInfo,
    OnewayRunningResponse,
)
from src.service.route.path_circular_random import random_walk_route
from src.service.route.path_oneway_dijkstra import dijkstra_route
from src.service.route.path_oneway_random import oneway_random_route
from src.service.route.path_utils import (
    extract_coordinates,
    find_nearest_node,
    prune_dead_ends,
)

# ?곕떇 紐⑤뱶?먯꽌 ?좏샇?섎뒗 肄붿뒪 ?좏삎
RUNNING_COURSE_TYPES = ["river", "park", "bike_track", "trail"]

# ?곕떇 紐⑤뱶 湲곕낯 ?쒓렇 ?꾪꽣
RUNNING_TAGS = ["?곕떇"]


# ??????????????????????????????????????????????????????????????
# ?대? ?ы띁
# ??????????????????????????????????????????????????????????????

def _apply_running_weights(
    G: nx.Graph,
    slope_weight: float = 1.0,
    type_bonus: float = 2.0,
) -> nx.Graph:
    """
    ?곕떇 紐⑤뱶 ?꾩슜 ``custom_score``瑜?媛??ｌ????명똿?⑸땲??

    ``circular_running_route`` / ``oneway_running_route`` ?몄텧 ?꾩뿉
    諛섎뱶??癒쇱? ?ㅽ뻾?댁빞 ?⑸땲?? 洹몃옒?꾨? in-place濡??섏젙?섍퀬 諛섑솚?⑸땲??

    媛以묒튂 怨듭떇::

        slope_factor        = 1.0 + slope_score * slope_weight
        effective_type_bonus = type_bonus  (river/park/bike_track/trail)
                             | 1.0         (?쇰컲 ?ｌ?)
        length_bonus        = 1.0 + log1p(length / 50.0)

        custom_score = (length * slope_factor)
                       / (safety * nature * effective_type_bonus * length_bonus + 1e-6)

    ``custom_score``媛 ??쓣?섎줉 寃쎈줈 ?먯깋 ?뚭퀬由ъ쬁???좏샇?⑸땲??

    Args:
        G            (nx.Graph) : ?ｌ???``length``, ``safety_score``, ``nature_score``,
                                  ``slope_score``, ``path_type`` ?띿꽦???덈뒗 洹몃옒??
        slope_weight (float)    : ?됱? ?좏샇?? ?믪쓣?섎줉 寃쎌궗 ?ｌ? ?섎꼸??媛뺥솕.
                                  踰붿쐞 沅뚯옣: 1.0 ~ 3.0. 湲곕낯媛?1.0.
        type_bonus   (float)    : 怨듭썝쨌?섏쿇 ?좏샇?? river / park / bike_track / trail
                                  path_type ?ｌ????곸슜?섎뒗 遺꾨え 諛곗닔.
                                  踰붿쐞 沅뚯옣: 1.0 ~ 3.0. 湲곕낯媛?2.0.

    Returns:
        nx.Graph: ``custom_score``媛 異붽???洹몃옒??(?낅젰 G? ?숈씪 媛앹껜).
    """
    PREFERRED_PATH_TYPES = {"river", "park", "bike_track", "trail"}

    for u, v, data in G.edges(data=True):
        length      = data.get("length", 1.0) or 1.0
        safety      = data.get("safety_score", 1.0) or 1.0
        nature      = data.get("nature_score", 1.0) or 1.0
        slope       = data.get("slope_score", 0.0) or 0.0
        path_type   = data.get("path_type", "") or ""

        # ?섏쿇쨌怨듭썝쨌?먯쟾嫄곕룄濡?蹂대꼫??(?뚮씪誘명꽣濡??쒖뼱)
        effective_type_bonus = type_bonus if path_type.lower() in PREFERRED_PATH_TYPES else 1.0

        # 寃쎌궗 ?⑤꼸?? slope_weight濡?媛뺣룄 議곗젅
        slope_factor = 1.0 + slope * slope_weight

        # 湲몄씠 蹂대꼫?? 湲??ｌ??쇱닔濡?遺꾨え 利앷? ??吏㏃? 怨⑤ぉ ?뚰뵾
        length_bonus = 1.0 + math.log1p(length / 50.0)

        custom_score = (length * slope_factor) / (safety * nature * effective_type_bonus * length_bonus + 1e-6)
        G[u][v]["custom_score"] = custom_score

    return G


def _build_result(
    G: nx.Graph,
    nodes: list,
    mode: str,
    matched_courses: list[dict],
) -> dict:
    """
    寃쎈줈 ?몃뱶 紐⑸줉???묐떟 ?뺤뀛?덈━濡?蹂?섑빀?덈떎.

    dead-end 媛吏移섍린(max_branch_length=300m) ??醫뚰몴 異붿텧 ??珥?嫄곕━ 怨꾩궛 ?쒖쑝濡?泥섎━?⑸땲??

    Args:
        G               (nx.Graph)   : 寃쎈줈 ?앹꽦???ъ슜??洹몃옒??
        nodes           (list[int])  : 寃쎈줈 ?몃뱶 ID 紐⑸줉.
        mode            (str)        : ?묐떟???ы븿??紐⑤뱶 臾몄옄??
                                       ?? ``"circular_running"``, ``"oneway_running_random"``
        matched_courses (list[dict]) : DB?먯꽌 議고쉶??異붿쿇 肄붿뒪 紐⑸줉 (洹몃?濡??꾨떖).

    Returns:
        dict: ?꾨옒 ?ㅻ? ?ы븿?섎뒗 ?뺤뀛?덈━.

        - ``mode``              (str)        : ?낅젰 ``mode`` 媛?
        - ``coordinates``       (list)       : ``[[lat, lon], ...]`` ?뺥깭??醫뚰몴 紐⑸줉.
        - ``total_distance_km`` (float)      : 媛吏移섍린 ??寃쎈줈??珥?嫄곕━ (km).
        - ``matched_courses``   (list[dict]) : ?낅젰 ``matched_courses`` 媛?
    """
    pruned = prune_dead_ends(nodes, G, max_branch_length=300)
    coords = extract_coordinates(G, pruned)
    total_m = sum(
        (G.get_edge_data(pruned[i], pruned[i + 1]) or {}).get("length", 0)
        for i in range(len(pruned) - 1)
    )
    return {
        "mode":               mode,
        "coordinates":        coords,
        "total_distance_km":  round(total_m / 1000, 2),
        "matched_courses":    matched_courses,  # DB?먯꽌 李얠? 異붿쿇 肄붿뒪 紐⑸줉
    }


# ??????????????????????????????????????????????????????????????
# 怨듦컻 API
# ??????????????????????????????????????????????????????????????

def get_circular_route(
    lat: float,
    lon: float,
    target_km: float = 5.0,
    radius_m: float = 5_000,
    G: Optional[nx.Graph] = None,
) -> CircularRunningResponse:
    """
    異쒕컻??湲곗? ?쒗솚(猷⑦봽) ?곕떇 肄붿뒪瑜?諛섑솚?⑸땲?? (**?먯껜 ?꾧껐??*)

    洹몃옒??濡쒕뱶쨌媛以묒튂 ?곸슜쨌寃쎈줈 ?앹꽦??紐⑤몢 ?대??먯꽌 泥섎━?⑸땲??
    ``circular_running_route()``? ?щ━ ?몃??먯꽌 G瑜?以鍮꾪븯嫄곕굹
    ``_apply_running_weights()``瑜??몄텧???꾩슂媛 ?놁뒿?덈떎.

    Args:
        lat       (float)              : 異쒕컻???꾨룄.
        lon       (float)              : 異쒕컻??寃쎈룄.
        target_km (float)              : 紐⑺몴 嫄곕━ (km). 湲곕낯媛?5.0.
        radius_m  (float)              : DB 肄붿뒪 寃??諛섍꼍 (誘명꽣). 湲곕낯媛?5,000.
        G         (nx.Graph, optional) : 誘몃━ 濡쒕뱶??洹몃옒?? ``None``?대㈃ DB?먯꽌 濡쒕뱶.

    Returns:
        dict: ?꾨옒 ?ㅻ? ?ы븿?섎뒗 ?뺤뀛?덈━.

        - ``mode``              (str)        : ``"circular_running"``
        - ``coordinates``       (list)       : ``[[lat, lon], ...]`` ?뺥깭??醫뚰몴 紐⑸줉.
        - ``total_distance_km`` (float)      : 珥?嫄곕━ (km).
        - ``matched_courses``   (list[dict]) : 諛섍꼍 ??DB 異붿쿇 肄붿뒪 紐⑸줉.
        - ``error``             (str)        : 寃쎈줈 ?앹꽦 ?ㅽ뙣 ?쒖뿉留??ы븿.
    """
    t0 = time.time()

    # ?? 1. DB 肄붿뒪 議고쉶 ????????????????????????????????????????
    matched_courses = RunningRepository.get_running_layer_near(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        is_circular=True,
        course_types=RUNNING_COURSE_TYPES,
        tags=RUNNING_TAGS,
        limit=5,
    )
    print(f"[running/circular] DB 肄붿뒪 {len(matched_courses)}嫄?議고쉶 ({time.time()-t0:.2f}s)")

    # ?? 2. 洹몃옒??濡쒕뱶 ?????????????????????????????????????????
    t1 = time.time()
    graph_radius = target_km * 1000 * 2.5  # 紐⑺몴 嫄곕━??2.5諛?諛섍꼍
    if G is None:
        G = GraphRepository.load_graph_near(lat, lon, radius_m=graph_radius)
    print(f"[running/circular] 洹몃옒??濡쒕뱶 ({time.time()-t1:.2f}s)")

    courses = [CourseInfo(**c) for c in matched_courses]

    if G.number_of_nodes() == 0:
        return CircularRunningResponse(
            mode="circular_running",
            coordinates=[],
            total_distance_km=0.0,
            matched_courses=courses,
            error="?대떦 ?꾩튂 二쇰???寃쎈줈 ?곗씠?곌? ?놁뒿?덈떎.",
        )

    # ?? 3. 醫뚰몴 ?녿뒗 ?몃뱶 ?쒓굅 (KeyError 諛⑹?) ????????????????
    invalid_nodes = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
    if invalid_nodes:
        G = G.copy()
        G.remove_nodes_from(invalid_nodes)
        print(f"[running/circular] 醫뚰몴 ?녿뒗 ?몃뱶 {len(invalid_nodes)}媛??쒓굅")

    if G.number_of_nodes() == 0:
        return CircularRunningResponse(
            mode="circular_running",
            coordinates=[],
            total_distance_km=0.0,
            matched_courses=courses,
            error="?좏슚???몃뱶媛 ?놁뒿?덈떎.",
        )

    # ?? 4. ?곕떇 媛以묒튂 ?곸슜 ????????????????????????????????????
    G = _apply_running_weights(G)

    # ?? 5. ?쒗솚 寃쎈줈 ?앹꽦 ??????????????????????????????????????
    t2 = time.time()
    start_node = find_nearest_node(G, lat, lon)
    raw = random_walk_route(G, start_node, target_km, weight="custom_score")
    print(f"[running/circular] 寃쎈줈 ?앹꽦 ({time.time()-t2:.2f}s)")

    result = _build_result(G, raw["nodes"], "circular_running", matched_courses)
    print(f"[running/circular] 珥??뚯슂 {time.time()-t0:.2f}s")
    return CircularRunningResponse(
        mode=result["mode"],
        coordinates=result["coordinates"],
        total_distance_km=result["total_distance_km"],
        matched_courses=courses,
    )


def get_oneway_route(
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
    target_km: Optional[float] = None,
    use_random: bool = True,
    radius_m: float = 5_000,
    G: Optional[nx.Graph] = None,
) -> OnewayRunningResponse:
    """
    異쒕컻?????꾩갑???몃룄 ?곕떇 肄붿뒪瑜?諛섑솚?⑸땲?? (**?먯껜 ?꾧껐??*)

    洹몃옒??濡쒕뱶쨌媛以묒튂 ?곸슜쨌寃쎈줈 ?앹꽦??紐⑤몢 ?대??먯꽌 泥섎━?⑸땲??
    ``use_random`` 媛믪뿉 ?곕씪 ?뚭퀬由ъ쬁??遺꾧린?⑸땲??

    Args:
        start_lat  (float)              : 異쒕컻???꾨룄.
        start_lon  (float)              : 異쒕컻??寃쎈룄.
        end_lat    (float)              : ?꾩갑???꾨룄.
        end_lon    (float)              : ?꾩갑??寃쎈룄.
        target_km  (float, optional)    : 紐⑺몴 嫄곕━ (km). ``use_random=True``???뚮쭔 ?ъ슜.
                                          ``None``?대㈃ 吏곸꽑 嫄곕━ 湲곕컲?쇰줈 ?먮룞 ?ㅼ젙.
        use_random (bool)               : ``True`` ??Edge Penalty ?고쉶 寃쎈줈 (oneway_random).
                                          ``False`` ??Dijkstra 理쒕떒 寃쎈줈.
        radius_m   (float)              : DB 肄붿뒪 寃??諛섍꼍 (誘명꽣). 湲곕낯媛?5,000.
        G          (nx.Graph, optional) : 誘몃━ 濡쒕뱶??洹몃옒?? ``None``?대㈃ DB?먯꽌 濡쒕뱶.

    Returns:
        dict: ?꾨옒 ?ㅻ? ?ы븿?섎뒗 ?뺤뀛?덈━.

        - ``mode``              (str)        : ``"oneway_running_random"`` ?먮뒗
                                               ``"oneway_running_shortest"``
        - ``coordinates``       (list)       : ``[[lat, lon], ...]`` ?뺥깭??醫뚰몴 紐⑸줉.
        - ``total_distance_km`` (float)      : 珥?嫄곕━ (km).
        - ``matched_courses``   (list[dict]) : 諛섍꼍 ??DB 異붿쿇 肄붿뒪 紐⑸줉.
        - ``error``             (str)        : 寃쎈줈 ?앹꽦 ?ㅽ뙣 ?쒖뿉留??ы븿.
    """
    t0 = time.time()

    # ?? 1. DB 肄붿뒪 議고쉶 ????????????????????????????????????????
    matched_courses = RunningRepository.get_running_layer_near(
        lat=start_lat,
        lon=start_lon,
        radius_m=radius_m,
        is_circular=False,
        course_types=RUNNING_COURSE_TYPES,
        tags=RUNNING_TAGS,
        limit=5,
    )
    print(f"[running/oneway] DB 肄붿뒪 {len(matched_courses)}嫄?議고쉶 ({time.time()-t0:.2f}s)")

    courses = [CourseInfo(**c) for c in matched_courses]

    # ?? 2. 洹몃옒??濡쒕뱶 ?????????????????????????????????????????
    t1 = time.time()
    straight_m = math.sqrt(
        (start_lat - end_lat) ** 2 + (start_lon - end_lon) ** 2
    ) * 111_000  # ?꾨룄 1????111km
    graph_radius = max(straight_m * 1.5, 3_000)  # 吏곸꽑 嫄곕━??1.5諛? 理쒖냼 3km

    if G is None:
        # 異쒕컻쨌?꾩갑 以묎컙 吏??湲곗??쇰줈 濡쒕뱶
        mid_lat = (start_lat + end_lat) / 2
        mid_lon = (start_lon + end_lon) / 2
        G = GraphRepository.load_graph_near(mid_lat, mid_lon, radius_m=graph_radius)
    print(f"[running/oneway] 洹몃옒??濡쒕뱶 ({time.time()-t1:.2f}s)")

    if G.number_of_nodes() == 0:
        return OnewayRunningResponse(
            mode="oneway_running",
            coordinates=[],
            total_distance_km=0.0,
            matched_courses=courses,
            error="?대떦 ?꾩튂 二쇰???寃쎈줈 ?곗씠?곌? ?놁뒿?덈떎.",
        )

    # ?? 3. 醫뚰몴 ?녿뒗 ?몃뱶 ?쒓굅 (KeyError 諛⑹?) ????????????????
    invalid_nodes = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
    if invalid_nodes:
        G = G.copy()
        G.remove_nodes_from(invalid_nodes)
        print(f"[running/oneway] 醫뚰몴 ?녿뒗 ?몃뱶 {len(invalid_nodes)}媛??쒓굅")

    if G.number_of_nodes() == 0:
        return OnewayRunningResponse(
            mode="oneway_running",
            coordinates=[],
            total_distance_km=0.0,
            matched_courses=courses,
            error="?좏슚???몃뱶媛 ?놁뒿?덈떎.",
        )

    # ?? 4. ?곕떇 媛以묒튂 ?곸슜 ????????????????????????????????????
    G = _apply_running_weights(G)

    # ?? 5. ?몃룄 寃쎈줈 ?앹꽦 ??????????????????????????????????????
    t2 = time.time()
    start_node = find_nearest_node(G, start_lat, start_lon)
    end_node   = find_nearest_node(G, end_lat, end_lon)

    if use_random and target_km:
        raw = oneway_random_route(G, start_node, end_node, target_km, weight="custom_score")
        mode_label = "oneway_running_random"
    else:
        raw = dijkstra_route(G, start_node, end_node, weight="custom_score")
        mode_label = "oneway_running_shortest"

    print(f"[running/oneway] 寃쎈줈 ?앹꽦 ({time.time()-t2:.2f}s)")

    result = _build_result(G, raw["nodes"], mode_label, matched_courses)
    print(f"[running/oneway] 珥??뚯슂 {time.time()-t0:.2f}s")
    return OnewayRunningResponse(
        mode=result["mode"],
        coordinates=result["coordinates"],
        total_distance_km=result["total_distance_km"],
        matched_courses=courses,
    )


