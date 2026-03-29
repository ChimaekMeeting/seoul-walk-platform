from dotenv import load_dotenv
import os
from redis import asyncio

load_dotenv()

VALKEY_URI = os.getenv("VALKEY_URI")

valkey_pool = asyncio.ConnectionPool.from_url(
    VALKEY_URI,
    decode_responses=True,
    ssl_cert_reqs=None
)

def get_valkey_db():
    """
    Valkey(Redis) 클라이언트를 반환합니다.
    """
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