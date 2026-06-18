from src.service import (
    KakaoLoginService,
    UserService,
    AuthService,
    PrewalkOrchestrator,
    RouteService
)
from src.agent.nodes import (
    WeatherChecker,
    Extractor,
    Interviewer,
    RouteExecutor
)
from src.infrastructure.external.client.kakao_client import KakaoClient
from src.repository.network.graph_repository import GraphRepository

# 싱글톤 패턴
auth_service        = AuthService()
user_service        = UserService(auth_service)
kakao_login_service = KakaoLoginService(user_service, auth_service)
weather_checker     = WeatherChecker()
route_service       = RouteService(G=GraphRepository.load_graph())

# route_service getter를 먼저 정의 — RouteTool.__init__에서 lazy import로 참조
def get_route_service() -> RouteService:
    return route_service

prewalk_orchestrator = PrewalkOrchestrator(
    weather_checker = weather_checker,
    kakao_client    = KakaoClient(),
    extractor       = Extractor(),
    interviewer     = Interviewer(),
    route_executor  = RouteExecutor(),
)

# --- 날씨 ---
def get_weather_checker() -> WeatherChecker:
    return weather_checker

# --- 사용자 인증 ---
def get_auth_service() -> AuthService:
    return auth_service

def get_user_service() -> UserService:
    return user_service

def get_kakao_login_service() -> KakaoLoginService:
    return kakao_login_service

# --- 챗봇 ---
def get_prewalk_orchestrator() -> PrewalkOrchestrator:
    return prewalk_orchestrator
