from dotenv import load_dotenv
import os
from redis import asyncio
from pathlib import Path
import ssl
import redis.asyncio as asyncio


load_dotenv()

VALKEY_URI = os.getenv("VALKEY_URI")

ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

valkey_pool = asyncio.ConnectionPool.from_url(
    VALKEY_URI,
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