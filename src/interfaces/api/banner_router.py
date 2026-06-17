"""
src/interfaces/api/banner_router.py

GET /api/banner 엔드포인트 정의
날씨 상태와 현재 시각을 기반으로 배너 목록을 반환
마라톤 이벤트(외부 API) → 시즌 배너 → 고정 배너 순으로 구성
"""
from datetime import datetime, date
import traceback
from typing import Optional

from fastapi import APIRouter, HTTPException

from src.infrastructure.external.client.marathon_client import MarathonClient
from src.infrastructure.external.schema.weather_schema import EnvironmentInfo
from src.service.route.banner_service import BannerService

router = APIRouter(tags=["banner"])


@router.get("/api/banner")
async def get_banner(
    weather_status: str = "",
    weather_msg: str = "",
    hour: Optional[int] = None,
):
    """
    input : weather_status, weather_msg, hour (선택)
    output: [{"emoji", "text", "sub", ...}, ...]

    BannerService의 asyncio.run() 충돌을 피하기 위해
    _fetch_all_events()를 직접 await해서 배너 목록 구성
    """
    try:
        service = BannerService(MarathonClient())
        weather = EnvironmentInfo(
            weather_status=weather_status,
            weather_msg=weather_msg,
            air_status="", air_msg="", display_msg="",
        )

        if hour is None:
            hour = datetime.now().hour

        banners = []

        # 이벤트 배너
        today  = date.today()
        events = await service._fetch_all_events()
        for event in events:
            diff = (event.date - today).days
            if -1 <= diff <= 14:
                banners.append(service._get_event_text({**event.model_dump(), "diff": diff}))
                break

        # 시즌 배너
        if service._is_hot(weather.weather_msg):
            if 6 <= hour < 9:
                banners.append(service.BANNERS["season"]["hot_morning"])
            elif service._is_humid(weather.weather_status):
                banners.append(service.BANNERS["season"]["hot_humid"])
            else:
                banners.append(service.BANNERS["season"]["hot_sunny"])

        # 고정 배너
        keys = (
            ["dog", "healing"] if hour < 17
            else ["dog", "healing", "night"] if hour < 21
            else ["night"]
        )
        for key in keys:
            banners.append(service.BANNERS["fixed"][key])

        return banners

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
