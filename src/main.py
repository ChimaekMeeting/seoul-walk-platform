from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from src.entity.base import init_db
from src.api import weather_router, user_router, prewalk_router

import uvicorn

app = FastAPI()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB 초기화
    # init_db()

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

@app.get("/")
def read_root():
    return {"message": "산책 경로 추천 서비스입니다."}

if __name__ == "__main__":
    uvicorn.run("src.main:app", host="127.0.0.1", port=8080, reload=True)