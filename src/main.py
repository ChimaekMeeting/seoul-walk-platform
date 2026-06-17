from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import uvicorn

from src.entity.base import init_db
from src.repository.network.graph_repository import GraphRepository
from src.service.route.route_service import RouteService
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
    app.state.G_full        = GraphRepository.load_graph()
    app.state.route_service = RouteService(G=app.state.G_full)
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
    uvicorn.run("src.main:app", host="127.0.0.1", port=8080, reload=True)