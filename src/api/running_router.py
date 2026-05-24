"""
런닝/다이어트 모드 API 라우터.

엔드포인트
----------
- ``POST /api/running/circular`` : 순환 코스 추천
- ``POST /api/running/oneway``   : 편도 코스 추천 (항상 우회 경로)

각 엔드포인트의 내부 처리 흐름
--------------------------------
1. ``load_graph_near()``         — 위치 기반 그래프 로드 (PostGIS)
2. 좌표 없는 노드 제거
3. ``_apply_running_weights()``  — 런닝 특화 ``custom_score`` 세팅
4. ``circular_running_route()``
   또는 ``oneway_running_route()``  — 경로 알고리즘 실행
5. Pydantic 스키마로 직렬화하여 반환

main.py 등록 방법 (팀원과 합의 후 추가)
----------------------------------------
    from src.api import running_router
    app.include_router(running_router.router)

의존 모듈
---------
- ``src.repository.route.graph_repository.load_graph_near``
- ``src.service.route.running_route_service._apply_running_weights``
- ``src.service.route.path_circular_running.circular_running_route``
- ``src.service.route.path_oneway_running.oneway_running_route``
"""

import math
import traceback

from fastapi import APIRouter, HTTPException

from src.schema.running_schema import (
    CircularRunningRequest,
    CircularRunningResponse,
    CourseInfo,
    OnewayRunningRequest,
    OnewayRunningResponse,
)
from src.repository.route.graph_repository import load_graph_near
from src.service.route.running_route_service import _apply_running_weights
from src.service.route.path_circular_running import circular_running_route
from src.service.route.path_oneway_running import oneway_running_route

router = APIRouter(
    prefix="/api/running",
    tags=["running"],
)


# ──────────────────────────────────────────────────────────────
# 순환 코스
# ──────────────────────────────────────────────────────────────

@router.post("/circular", response_model=CircularRunningResponse)
async def circular_running(request: CircularRunningRequest):
    """
    출발점 기준 순환(루프) 런닝 코스를 추천합니다.

    - 하천변·공원 위주 경로를 선호합니다.
    - DB에서 반경 내 순환 코스 목록도 함께 반환합니다.

    **요청 예시**
    ```json
    {
        "lat": 37.5285,
        "lng": 126.9326,
        "target_km": 5.0,
        "radius_m": 5000
    }
    ```
    """
    try:
        graph_radius = request.target_km * 1000 * 2.5
        G = load_graph_near(request.lat, request.lng, radius_m=graph_radius)

        if G.number_of_nodes() == 0:
            return CircularRunningResponse(
                mode="circular_running",
                coordinates=[],
                total_distance_km=0.0,
                matched_courses=[],
                error="해당 위치 주변에 경로 데이터가 없습니다.",
            )

        invalid = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
        if invalid:
            G = G.copy()
            G.remove_nodes_from(invalid)

        G = _apply_running_weights(G)

        result = circular_running_route(
            G=G,
            start_lat=request.lat,
            start_lng=request.lng,
            target_m=request.target_km * 1000,
            radius_m=request.radius_m,
            session=None,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    return CircularRunningResponse(
        mode=result.get("mode", "circular_running"),
        coordinates=result.get("coordinates", []),
        total_distance_km=result.get("total_distance_km", 0.0),
        matched_courses=[CourseInfo(**c) for c in result.get("matched_courses", [])],
        error=result.get("error"),
    )


# ──────────────────────────────────────────────────────────────
# 편도 코스
# ──────────────────────────────────────────────────────────────

@router.post("/oneway", response_model=OnewayRunningResponse)
async def oneway_running(request: OnewayRunningRequest):
    """
    출발점 → 도착점 편도 런닝 코스를 추천합니다.

    - `use_random=true` : 하천변·공원을 경유하는 우회 경로 (더 긴 거리)
    - `use_random=false`: 최단 경로 (Dijkstra)

    **요청 예시**
    ```json
    {
        "start_lat": 37.5121,
        "start_lng": 126.9994,
        "end_lat": 37.5228,
        "end_lng": 126.9706,
        "target_km": 6.0,
        "use_random": true,
        "radius_m": 5000
    }
    ```
    """
    try:
        straight_m = math.sqrt(
            (request.start_lat - request.end_lat) ** 2 +
            (request.start_lng - request.end_lng) ** 2
        ) * 111_000
        graph_radius = max(straight_m * 1.5, 3_000)
        mid_lat = (request.start_lat + request.end_lat) / 2
        mid_lng = (request.start_lng + request.end_lng) / 2
        G = load_graph_near(mid_lat, mid_lng, radius_m=graph_radius)

        if G.number_of_nodes() == 0:
            return OnewayRunningResponse(
                mode="oneway_running",
                coordinates=[],
                total_distance_km=0.0,
                matched_courses=[],
                error="해당 위치 주변에 경로 데이터가 없습니다.",
            )

        invalid = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
        if invalid:
            G = G.copy()
            G.remove_nodes_from(invalid)

        G = _apply_running_weights(G)

        result = oneway_running_route(
            G=G,
            start_lat=request.start_lat,
            start_lng=request.start_lng,
            dest_lat=request.end_lat,
            dest_lng=request.end_lng,
            target_m=(request.target_km or 5.0) * 1000,
            radius_m=request.radius_m,
            session=None,
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

    return OnewayRunningResponse(
        mode=result.get("mode", "oneway_running"),
        coordinates=result.get("coordinates", []),
        total_distance_km=result.get("total_distance_km", 0.0),
        matched_courses=[CourseInfo(**c) for c in result.get("matched_courses", [])],
        error=result.get("error"),
    )
