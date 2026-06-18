"""
src/interfaces/api/map_router.py

지도 레이어 데이터 조회 엔드포인트 정의
카카오 시설(외부 API), DB 포인트, DB 엣지 3가지 데이터 소스를 각각 제공
"""
import json
import traceback
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from src.interfaces.dependencies import get_map_service
from src.service import MapService

router = APIRouter(
    prefix="/api/map",
    tags=["map"],
)


@router.get("/facilities")
async def get_facilities(
    lat: float,
    lon: float,
    category_code: Optional[str] = None,
    keyword: Optional[str] = None,
    radius: int = 2000,
    service: MapService = Depends(get_map_service)
):
    """
    input : lat, lon, category_code, keyword, radius
    output: [{"name", "lon", "lat", "address"}, ...]

    카카오 장소 API로 시설 목록을 조회해 반환
    """
    try:
        places = await service.fetch_kakao_facilities(
            lat, lon, category_code=category_code, keyword=keyword, radius=radius
        )
        return [
            {"name": p.place_name, "lon": float(p.x), "lat": float(p.y), "address": p.address_name}
            for p in places
        ]
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/points")
def get_points(
    lat: float,
    lon: float,
    table_name: str,
    type_col: Optional[str] = None,
    type_val: Optional[str] = None,
    radius_m: int = 2000,
    service: MapService = Depends(get_map_service)
):
    """
    input : lat, lon, table_name, type_col, type_val, radius_m
    output: [{"lat", "lon"}, ...]

    DB에서 반경 내 포인트 레이어 데이터를 조회해 반환
    지원하지 않는 table_name 입력 시 400 반환
    """
    try:
        df = service.fetch_db_points(lat, lon, table_name, type_col, type_val, radius_m)
        return df.to_dict(orient="records")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/edges")
def get_edges(
    lat: float,
    lon: float,
    radius_m: int = 2000,
    service: MapService = Depends(get_map_service)
):
    """
    input : lat, lon, radius_m
    output: [{"path": [[lon, lat], ...], "link_id": str}, ...]

    DB에서 반경 내 도보 네트워크 엣지를 조회하고 GeoJSON geometry를 좌표 배열로 변환해 반환
    """
    try:
        df = service.fetch_db_lines(lat, lon, radius_m)
        if df.empty:
            return []
        df["path"] = df["geometry"].apply(lambda x: json.loads(x)["coordinates"])
        return df[["path", "link_id"]].to_dict(orient="records")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
