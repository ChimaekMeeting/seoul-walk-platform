"""
런닝/다이어트 모드 API 라우터

엔드포인트
----------
POST /api/running/circular  → 순환 코스 추천
POST /api/running/oneway    → 편도 코스 추천

main.py 등록 방법 (팀원과 합의 후 추가)
----------------------------------------
    from src.api import running_router
    app.include_router(running_router.router)
"""

from fastapi import APIRouter, HTTPException
import traceback

from src.schema.running_schema import (
    CircularRunningRequest,
    CircularRunningResponse,
    CourseInfo,
    OnewayRunningRequest,
    OnewayRunningResponse,
)
from src.service.route.running_route_service import (
    get_circular_route,
    get_oneway_route,
)

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
        result = get_circular_route(
            lat=request.lat,
            lng=request.lng,
            target_km=request.target_km,
            radius_m=request.radius_m,
        )
    except Exception as e:
        traceback.print_exc()  # 터미널에 전체 에러 출력
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
        result = get_oneway_route(
            start_lat=request.start_lat,
            start_lng=request.start_lng,
            end_lat=request.end_lat,
            end_lng=request.end_lng,
            target_km=request.target_km,
            use_random=request.use_random,
            radius_m=request.radius_m,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return OnewayRunningResponse(
        mode=result.get("mode", "oneway_running"),
        coordinates=result.get("coordinates", []),
        total_distance_km=result.get("total_distance_km", 0.0),
        matched_courses=[CourseInfo(**c) for c in result.get("matched_courses", [])],
        error=result.get("error"),
    )
