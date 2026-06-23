from src.config.settings import settings  # noqa: F401 — LangSmith 트레이싱 활성화를 위해 최상단에 위치
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from src.entity.base import init_db
from src.interfaces.dependencies import init_route_service
from src.interfaces.api import (
    auth_router,
    login_router,
    prewalk_router,
    user_router,
    weather_router,
    walk_router,
    health_router,
    map_router,
    banner_router,
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_route_service()
    yield

app = FastAPI(
    title="산책 경로 추천 서비스",
    description="산책 경로 추천 API 서버",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

app.include_router(weather_router.router)
app.include_router(user_router.router)
app.include_router(prewalk_router.router)
app.include_router(auth_router.router)
app.include_router(login_router.router)
app.include_router(walk_router.router)
app.include_router(health_router.router)
app.include_router(map_router.router)
app.include_router(banner_router.router)

@app.get("/")
def read_root():
    return {"message": "산책 경로 추천 서비스입니다."}

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="127.0.0.1", port=8000, reload=True)
