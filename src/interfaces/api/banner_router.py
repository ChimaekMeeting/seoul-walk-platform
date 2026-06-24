import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from src.interfaces.dependencies import get_banner_service
from src.interfaces.schema.banner_schema import BannerResponse
from src.service.route.banner_service import BannerService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["banner"])


@router.get("/api/banner", response_model=BannerResponse)
async def get_banner(
    lat: float,
    lon: float,
    hour: Optional[int] = None,
    service: BannerService = Depends(get_banner_service),
):
    try:
        return await service.get_banner_list(lat, lon, hour)
    except Exception as e:
        logger.exception("banner_router_unexpected_error | lat=%s | lon=%s", lat, lon)
        raise HTTPException(status_code=500, detail=str(e))
