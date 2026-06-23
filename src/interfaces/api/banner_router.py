import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src.interfaces.dependencies import get_banner_service
from src.service.route.banner_service import BannerService

router = APIRouter(tags=["banner"])


@router.get("/api/banner")
async def get_banner(
    lat: float,
    lon: float,
    hour: Optional[int] = None,
    service: BannerService = Depends(get_banner_service),
):
    try:
        return await service.get_banner_list(lat, lon, hour)
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
