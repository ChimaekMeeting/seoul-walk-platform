import json
from typing import Optional

from src.infrastructure.cache.valkey import get_valkey_db

TTL_SECONDS = 1800  # 30분


class WeatherCacheRepository:
    @staticmethod
    async def get_weather(nx: int, ny: int) -> Optional[dict]:
        """
        기상청 격자 좌표(nx, ny)에 대한 캐시된 날씨 데이터를 조회합니다.
        """
        redis = get_valkey_db()
        key = f"weather:{nx}:{ny}"

        raw_data = await redis.get(key)
        if not raw_data:
            return None

        return json.loads(raw_data)

    @staticmethod
    async def save_weather(nx: int, ny: int, data: dict) -> None:
        """
        기상청 격자 좌표(nx, ny)에 날씨 데이터를 TTL 30분으로 캐싱합니다.
        """
        redis = get_valkey_db()
        key = f"weather:{nx}:{ny}"

        json_data = json.dumps(data, ensure_ascii=False)
        await redis.set(key, json_data, ex=TTL_SECONDS)

    @staticmethod
    async def get_air_quality(nx: int, ny: int) -> Optional[dict]:
        """
        기상청 격자 좌표(nx, ny)에 대한 캐시된 대기질 데이터를 조회합니다.
        """
        redis = get_valkey_db()
        key = f"air_quality:{nx}:{ny}"

        raw_data = await redis.get(key)
        if not raw_data:
            return None

        return json.loads(raw_data)

    @staticmethod
    async def save_air_quality(nx: int, ny: int, data: dict) -> None:
        """
        기상청 격자 좌표(nx, ny)에 대기질 데이터를 TTL 30분으로 캐싱합니다.
        """
        redis = get_valkey_db()
        key = f"air_quality:{nx}:{ny}"

        json_data = json.dumps(data, ensure_ascii=False)
        await redis.set(key, json_data, ex=TTL_SECONDS)
