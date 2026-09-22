import logging
from typing import Optional

from src.config.settings import settings
from src.service import (
    KakaoLoginService,
    UserService,
    AuthService,
    PrewalkOrchestrator,
    RouteService,
    BannerService,
    MapService,
    GpsArtService,
    SurveyService,
    LongTermProfileService,
)
from src.agent.nodes import (
    Extractor,
    WeightExtractor,
    Interviewer,
    ConfirmationClassifier,
    RouteExecutor
)
from src.infrastructure.external.client import (
    KakaoClient,
    MarathonClient,
    WeatherClient
)
from src.repository.network.graph_artifact_repository import (
    GraphArtifactRepository,
)
from src.repository.network.graph_repository import GraphRepository
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.alt_runtime import attach_alt_heuristic, prepare_alt_heuristic
from src.route_engine.weighted_cost_runtime import attach_weighted_cost, prepare_weighted_cost

logger = logging.getLogger(__name__)

# 싱글톤 패턴
auth_service        = AuthService()
user_service        = UserService(auth_service)
kakao_login_service = KakaoLoginService(user_service, auth_service)
kakao_client        = KakaoClient()
weather_client      = WeatherClient(kakao_client)
banner_service      = BannerService(MarathonClient(), weather_client)
map_service         = MapService(kakao_client)
survey_service      = SurveyService(auth_service)
gps_art_service     = GpsArtService(auth_service)
longterm_profile_service = LongTermProfileService(auth_service)

G = None
route_service: Optional[RouteService] = None
prewalk_orchestrator: Optional[PrewalkOrchestrator] = None

# lifespan에서 호출
def load_runtime_graph():
    if settings.WALK_GRAPH_SOURCE == "artifact":
        logger.info(
            "배포용 Graph artifact를 로드합니다: %s",
            settings.WALK_GRAPH_ARTIFACT_PATH,
        )
        return GraphArtifactRepository.load(
            settings.WALK_GRAPH_ARTIFACT_PATH,
            expected_data_version=settings.WALK_GRAPH_DATA_VERSION,
            expected_source_commit=settings.WALK_GRAPH_EXPECTED_COMMIT or None,
        )
    logger.info("PostgreSQL에서 도보 Graph를 생성합니다.")
    return GraphRepository.load_graph()


def init_route_service():
    global G, route_service, prewalk_orchestrator
    G             = load_runtime_graph()
    # 장기 프로필 SGD의 안전 특성값(1 - unsafe)이 탐색 비용식과 같은 비율을 쓰도록 설정값을 넘긴다.
    precompute_scoring_features(G, unsafe_accident_ratio=settings.WALK_UNSAFE_ACCIDENT_RATIO)
    # ALT 휴리스틱은 그래프에 붙여 두고 OnewayAstarEngine이 알아서 집어 쓴다 —
    # RouteService와 route_service.py는 이 때문에 바뀌지 않는다. 준비에 실패하면
    # (None, None)이 와서 아무것도 붙지 않고 엔진이 Haversine으로 돌아간다.
    alt_heuristic, alt_info = prepare_alt_heuristic(
        G,
        enabled=settings.WALK_ALT_ENABLED,
        method=settings.WALK_ALT_METHOD,
        k=settings.WALK_ALT_K,
        seed=settings.WALK_ALT_SEED,
    )
    attach_alt_heuristic(G, alt_heuristic, alt_info)
    # 점수 적재 상태(O(E), 실측 약 0.30초)도 기동 때 한 번만 재서 그래프에 붙인다.
    # 요청은 여기 붙은 적재율·중앙값만 읽어 자기 alpha/beta로 비용 객체를 만든다 —
    # 사용자별 가중치는 그래프에 붙이지 않는다.
    attach_weighted_cost(G, prepare_weighted_cost(
        G,
        enabled=settings.WALK_WEIGHTED_COST_ENABLED,
        coverage_min_ratio=settings.WALK_SCORE_COVERAGE_MIN,
    ))
    route_service = RouteService(G=G, auth_service=auth_service)
    prewalk_orchestrator = PrewalkOrchestrator(
        kakao_client            = kakao_client,
        auth_service            = auth_service,
        extractor               = Extractor(),
        weight_extractor        = WeightExtractor(),
        interviewer             = Interviewer(route_service=route_service),
        confirmation_classifier = ConfirmationClassifier(),
        route_executor          = RouteExecutor(),
    )

# 날씨
def get_weather_client() -> WeatherClient:
    return weather_client

# 사용자 인증
def get_auth_service() -> AuthService:
    return auth_service

def get_user_service() -> UserService:
    return user_service

def get_kakao_login_service() -> KakaoLoginService:
    return kakao_login_service

# 챗봇
def get_prewalk_orchestrator() -> PrewalkOrchestrator:
    return prewalk_orchestrator

# 경로
def get_route_service() -> RouteService:
    return route_service

# 배너
def get_banner_service() -> BannerService:
    return banner_service

# 지도
def get_map_service() -> MapService:
    return map_service

# 온보딩 설문
def get_survey_service() -> SurveyService:
    return survey_service

# GPS Art
def get_gps_art_service() -> GpsArtService:
    return gps_art_service

# 산책 후 피드백 / 장기 프로필
def get_longterm_profile_service() -> LongTermProfileService:
    return longterm_profile_service
