"""
src/interfaces/api/map_router.py

지도 레이어 데이터 조회 엔드포인트 정의
카카오 시설(외부 API), DB 포인트, DB 엣지 3가지 데이터 소스를 각각 제공
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends

from src.interfaces.dependencies import get_map_service
from src.interfaces.errors import SAFE_INTERNAL_ERROR_DETAIL, log_unexpected_error
from src.interfaces.schema.map_schema import (
    FacilityResponse,
    PointResponse,
    EdgeResponse,
)
from src.service import MapService

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/map",
    tags=["map"],
)


@router.get("/facilities", response_model=list[FacilityResponse])
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
        log_unexpected_error(logger, "map_facilities_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e


@router.get("/points/safety", response_model=list[PointResponse])
def get_safety_points(
    lat: float,
    lon: float,
    radius_m: int = 2000,
    service: MapService = Depends(get_map_service)
):
    """
    input : lat, lon, radius_m
    output: [{"lat", "lon", "category"}, ...]

    DB에서 반경 내 안전 시설물 포인트 전체를 조회해 반환
    카테고리(cctv/streetlight) 필터링은 클라이언트가 수행
    """
    try:
        df = service.fetch_safety_points(lat, lon, radius_m)
        return df.to_dict(orient="records")
    except Exception as e:
        log_unexpected_error(logger, "map_safety_points_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e


@router.get("/points/nature", response_model=list[PointResponse])
def get_nature_points(
    lat: float,
    lon: float,
    radius_m: int = 2000,
    service: MapService = Depends(get_map_service)
):
    """
    input : lat, lon, radius_m
    output: [{"lat", "lon", "category"}, ...]

    DB에서 반경 내 녹지 포인트 전체를 조회해 반환
    카테고리(green_type) 필터링은 클라이언트가 수행
    """
    try:
        df = service.fetch_nature_points(lat, lon, radius_m)
        return df.to_dict(orient="records")
    except Exception as e:
        log_unexpected_error(logger, "map_nature_points_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e


@router.get("/edges", response_model=list[EdgeResponse])
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
        log_unexpected_error(logger, "map_edges_unexpected_error", e)
        raise HTTPException(status_code=500, detail=SAFE_INTERNAL_ERROR_DETAIL) from e
