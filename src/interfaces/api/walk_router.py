import traceback

from fastapi import APIRouter, HTTPException

from src.interfaces.schema.walk_schema import WalkRouteRequest, WalkRouteResponse
from src.service.route.route_service import RouteService
from src.route_engine.engines.circular.child import CircularChildEngine
from src.route_engine.engines.oneway.child import OnewayChildEngine
from src.route_engine.schema import CircularRouteInput, OnewayRouteInput
from src.repository.network.graph_repository import GraphRepository

router = APIRouter(
    prefix="/api/walk",
    tags=["walk"],
)


@router.post("/route", response_model=WalkRouteResponse)
async def walk_route(request: WalkRouteRequest):
    """출발지 기반 산책 경로를 추천합니다."""
    try:
        start_lat   = request.origin.coordinate.lat
        start_lon   = request.origin.coordinate.lon
        distance_km = request.distance_km
        
        # profile_name을 한 번만 정규화하여 하위 분기 및 엔진 호출 시 일관되게 사용
        profile_name = request.profile_name.lower().strip() if request.profile_name else "default"
        
        # child_friendly 플래그나 profile_name이 child일 경우 모두 child 전용 엔진으로 라우팅
        if request.child_friendly or profile_name == "child":
            radius_m = distance_km * 1000 * 3.0
            G_raw    = GraphRepository.load_graph_near(start_lat, start_lon, radius_m=radius_m)
            G        = RouteService().extract_subgraph_near(G_raw, start_lat, start_lon, radius_m)

            if request.mode == "circular":
                inp    = CircularRouteInput(start_lat=start_lat, start_lon=start_lon, target_km=distance_km)
                engine = CircularChildEngine(inp, G)
            else:
                if not request.destination:
                    raise HTTPException(status_code=400, detail="편도 모드에서는 목적지가 필요합니다")
                inp = OnewayRouteInput(
                    start_lat=start_lat, start_lon=start_lon,
                    end_lat=request.destination.coordinate.lat,
                    end_lon=request.destination.coordinate.lon,
                    target_km=distance_km,
                )
                engine = OnewayChildEngine(inp, G, use_random=(request.mode == "oneway_random"))

            output = engine.run()
            return WalkRouteResponse(
                mode=output.mode,
                coordinates=output.coordinates,
                total_distance_km=output.total_km,
                error=output.fallback_reason.value if output.fallback_reason else None,
            )

        else:
            radius_m = distance_km * 1000 * 3.0
            G_full   = GraphRepository.load_graph_near(start_lat, start_lon, radius_m=radius_m)
            context  = {
                "mode":         request.mode,
                "distance_km":  distance_km,
                "origin": {
                    "place_name": request.origin.place_name,
                    "address":    request.origin.address,
                    "coordinate": {"lat": start_lat, "lon": start_lon},
                },
                "destination": (
                    {
                        "place_name": request.destination.place_name,
                        "address":    request.destination.address,
                        "coordinate": {
                            "lat": request.destination.coordinate.lat,
                            "lon": request.destination.coordinate.lon,
                        },
                    }
                    if request.destination else None
                ),
                "purpose": request.purpose,
            }
            # API 요청의 정규화된 profile_name을 RouteService의 profile layer까지 명시적으로 전달
            return RouteService().get_route(context, G_full=G_full, profile_name=profile_name)

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
