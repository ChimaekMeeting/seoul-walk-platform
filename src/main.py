from src.config.settings import settings  # noqa: F401 — LangSmith 트레이싱 활성화를 위해 최상단에 위치
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging
import uvicorn

from src.config.logging import setup_logging
from src.entity.base import init_db
from src.interfaces.errors import SAFE_INTERNAL_ERROR_DETAIL, log_unexpected_error
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
    setup_logging()
    init_db()
    init_route_service()
    yield

app = FastAPI(
    title="산책 경로 추천 서비스",
    description="산책 경로 추천 API 서버",
    lifespan=lifespan
)

logger = logging.getLogger(__name__)


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """입력값·내부 예외 객체를 되비추지 않는 JSON-safe 422 응답을 반환합니다."""
    details = [
        {
            key: error[key]
            for key in ("type", "loc", "msg")
            if key in error
        }
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": details})


@app.exception_handler(Exception)
async def unexpected_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    route = request.scope.get("route")
    route_path = getattr(route, "path", "unmatched")
    log_unexpected_error(
        logger,
        f"unhandled_api_error | method={request.method} | route={route_path}",
        exc,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": SAFE_INTERNAL_ERROR_DETAIL},
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "*",
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
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True)
