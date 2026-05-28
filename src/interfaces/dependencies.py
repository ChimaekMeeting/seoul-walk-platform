from src.service.user.login_service import KakaoLoginService
from src.service.user.user_service import UserService
from src.service.user.auth_service import AuthService
from src.service.chat.prewalk_service import PrewalkOrchestrator
from src.agent.nodes.weather_checker import WeatherChecker
from src.agent.nodes.extractor import Extractor
from src.agent.nodes.interviewer import Interviewer
from src.agent.nodes.weight_assigner import WeightAssigner
from src.infrastructure.external.client.kakao_client import KakaoClient

# 이 파일에서 정의된 서비스 객체를 다른 API 파일에서 전역적으로 사용하시면 됩니다!

# 싱글톤 패턴
auth_service        = AuthService()
user_service        = UserService(auth_service)
kakao_login_service = KakaoLoginService(user_service, auth_service)
weather_checker = WeatherChecker()

prewalk_orchestrator = PrewalkOrchestrator(
    weather_checker = weather_checker,
    kakao_client    = KakaoClient(),
    extractor       = Extractor(),
    interviewer     = Interviewer(),
    weight_assigner = WeightAssigner(),
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