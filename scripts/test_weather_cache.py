"""
WeatherChecker의 Valkey 캐싱을 검증하는 일회성 스크립트.
같은 좌표로 두 번 호출해서, 두 번째 호출은 실제 API를 부르지 않고 캐시된 값을 쓰는지 확인합니다.
실행: poetry run python scripts/test_weather_cache.py
(Valkey가 떠 있어야 합니다. DB·경로 그래프는 필요 없습니다.)
"""
import asyncio
from unittest.mock import AsyncMock, patch

from src.agent.nodes.weather_checker import WeatherChecker
from src.infrastructure.external.client.weather_client import WeatherClient
from src.infrastructure.external.client.kakao_client import KakaoClient
from src.infrastructure.cache.valkey import get_valkey_db

LAT, LON = 37.5665, 126.9780  # 서울시청


async def main():
    weather_client = WeatherClient(KakaoClient())
    checker = WeatherChecker(weather_client=weather_client)

    # 이전 실행에서 남은 캐시 제거
    nx, ny = weather_client.get_nx_and_ny(LAT, LON)
    redis = get_valkey_db()
    await redis.delete(f"weather:{nx}:{ny}", f"air_quality:{nx}:{ny}")
    print(f"[0] 격자 좌표: nx={nx}, ny={ny} (캐시 초기화 완료)")

    fake_weather = {"temperature": "20℃"}
    fake_air = {"pm10": "30㎍/㎥"}

    with patch.object(weather_client, "get_weather", AsyncMock(return_value=fake_weather)) as mock_weather, \
         patch.object(weather_client, "get_air_quality", AsyncMock(return_value=fake_air)) as mock_air:

        # 1차 호출 -> 캐시 없음 -> mock API가 호출돼야 함
        await checker.run(LAT, LON)
        print(f"[1] 1차 호출 후 get_weather 호출 횟수: {mock_weather.call_count}")
        print(f"[1] 1차 호출 후 get_air_quality 호출 횟수: {mock_air.call_count}")
        assert mock_weather.call_count == 1
        assert mock_air.call_count == 1
        print("[1] PASS")

        # 2차 호출(같은 좌표) -> 캐시 히트 -> mock API 호출 횟수가 그대로여야 함
        await checker.run(LAT, LON)
        print(f"[2] 2차 호출 후 get_weather 호출 횟수: {mock_weather.call_count}")
        print(f"[2] 2차 호출 후 get_air_quality 호출 횟수: {mock_air.call_count}")
        assert mock_weather.call_count == 1, "캐시 히트인데 API가 다시 호출됐습니다."
        assert mock_air.call_count == 1, "캐시 히트인데 API가 다시 호출됐습니다."
        print("[2] PASS: 두 번째 호출에서 캐시가 재사용됐습니다.")

    # TTL 확인
    ttl_weather = await redis.ttl(f"weather:{nx}:{ny}")
    ttl_air = await redis.ttl(f"air_quality:{nx}:{ny}")
    print(f"[3] weather TTL: {ttl_weather}초, air_quality TTL: {ttl_air}초")
    assert 0 < ttl_weather <= 1800
    assert 0 < ttl_air <= 1800
    print("[3] PASS: TTL이 30분 이내로 설정되어 있습니다.")

    print("\n모두 통과했습니다.")


if __name__ == "__main__":
    asyncio.run(main())
