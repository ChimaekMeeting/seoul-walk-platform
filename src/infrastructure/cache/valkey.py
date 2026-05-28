from dotenv import load_dotenv
import os
import redis.asyncio as asyncio

load_dotenv()

valkey_pool = asyncio.ConnectionPool.from_url(
    os.getenv("VALKEY_URI"),
    decode_responses=True,
)

def get_valkey_db():
    return asyncio.Redis(connection_pool=valkey_pool)

async def health_check_valkey() -> bool:
    """
    Valkey(Redis) 연결 상태를 비동기로 확인합니다.
    """
    client = get_valkey_db()
    try:
        return await client.ping()
    except Exception as e:
        return False
    finally:
        await client.aclose()