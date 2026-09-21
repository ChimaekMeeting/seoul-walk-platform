"""
tests/integration/test_route_feedback_flow.py

RouteService.get_route() -> RouteHistory.candidate_features 스냅샷 -> LongTermProfileService.
submit_feedback()으로 이어지는 흐름을 하나의 테스트에서 검증한다.

기존 단위 테스트(test_routue_service.py/test_longterm_profile_service.py)는 각 서비스를
따로따로, candidate_features를 이미 주어진 값으로 모킹해서 검증한다. 이 파일은 그 둘을
이어서 "경로 생성 시점에 얼린 candidate_features가 피드백 시점까지 그대로 전달되는가"
자체를 검증한다 — candidate_features 스냅샷 메커니즘을 도입한 이유(그래프/엔진 상태가
피드백 시점엔 사라지므로 생성 시점에 미리 계산해 얼려둔다)가 실제로 지켜지는지 보는
회귀 테스트다.

2026-09-17 로컬 API 실측(Docker Postgres/Valkey + 실제 서울 그래프)에서 확인한 4개 케이스를
결정적인 가짜 엔진/리포지토리로 재현한다:
  - 후보 1개(candidate_feature_vectors 없음, 예: oneway_shortest류) -> insufficient_candidates
  - 후보 3개 -> success, feedback_count가 호출마다 1씩 증가

engine.candidate_feature_vectors는 duck-typing으로 읽히므로(route_service.py 참고), 이
흐름은 RouteService.base_engines에 어떤 엔진이 매핑돼 있는지와 무관하게 성립한다 — 그래서
GRASP+ALNS 엔진이 아직 route_service에 연결되지 않은 상태에서도 이 계약 자체는 가짜 엔진으로
완전히 검증할 수 있다.
"""
import asyncio
from unittest.mock import MagicMock, patch

import networkx as nx
import pytest

from src.agent.nodes.route_executor import MODE_TOOL_MAP, RouteExecutor
from src.agent.tools.route_tools import RouteTool
from src.interfaces.schema.auth_schema import Status
from src.interfaces.schema.route_feedback_schema import RouteFeedbackRequest, RouteFeedbackStatus
from src.interfaces.schema.walk_schema import Coordinate, WalkMode, WalkRouteResponse, WalkRouteStatus
from src.route_engine.engines.circular_grasp_waypoint_alns import CircularGraspWaypointAlnsEngine
from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.engines.waypoint_engine_assembly import CANDIDATE_COUNT
from src.schema.prewalk_schema import CircularPreference, Location, State
from src.schema.route_schema import CircularRouteInput
from src.service.route.route_service import MIN_CANDIDATES_FOR_PROFILE, RouteService
from src.service.user import longterm_profile_service as longterm_profile_module
from src.service.user.longterm_profile_service import LongTermProfileService

ACCESS_TOKEN = "valid-token"
ORIGIN = Coordinate(lat=37.5, lon=127.0)

_SUCCESS_CANDIDATE_FEATURES = [
    {"safety": 0.8, "comfort": 0.95},
    {"safety": 0.85, "comfort": 0.4},
    {"safety": 0.82, "comfort": 0.45},
]


class _FakeRouteHistoryStore:
    """RouteHistoryRepository.save/find_by_id를 흉내 내는 메모리 저장소.

    MagicMock의 고정 반환값 대신 실제로 저장된 candidate_features를 그대로 돌려줘야
    "생성 시점 값이 피드백 시점까지 전달되는가"를 검증할 수 있다.
    """

    def __init__(self):
        self._rows: dict[int, MagicMock] = {}
        self._next_id = 1

    def save(self, **kwargs) -> MagicMock:
        history = MagicMock(id=self._next_id, **kwargs)
        self._rows[self._next_id] = history
        self._next_id += 1
        return history

    def find_by_id(self, history_id: int, user_id: int):
        row = self._rows.get(history_id)
        return row if row is not None and row.user_id == user_id else None


class _FakePreferenceStore:
    """UserPreferenceRepository.get_by_user_id/upsert를 흉내 내는 메모리 저장소."""

    def __init__(self):
        self._row = None

    def get_by_user_id(self, user_id: int):
        return self._row

    def upsert(self, user_id: int, **kwargs) -> MagicMock:
        self._row = MagicMock(user_id=user_id, **kwargs)
        return self._row


def _engine_stub(total_km: float, candidate_feature_vectors: list[dict[str, float]] | None):
    """route_service.base_engines[mode]에 꽂아 넣을 가짜 엔진 클래스.

    실제 beam/GRASP 탐색 없이 run()의 후보 개수와 candidate_feature_vectors를 자유롭게
    지정한다 — 진짜 서울 그래프로 정확히 1개/3개 후보를 강제로 재현하는 건 비결정적이라
    이 흐름의 회귀 테스트로는 적합하지 않다. candidate_feature_vectors가 None이면
    oneway_shortest처럼 이 속성 자체가 없는 엔진(다양화 미지원)을 흉내 낸다.
    """
    n = len(candidate_feature_vectors) if candidate_feature_vectors else 1
    responses = [
        WalkRouteResponse(
            status=WalkRouteStatus.SUCCESS,
            mode=WalkMode.CIRCULAR_RANDOM,
            coordinates=[[37.5, 127.0], [37.51, 127.01], [37.5, 127.0]],
            total_km=total_km,
        )
        for _ in range(n)
    ]
    if candidate_feature_vectors is None:
        instance = MagicMock(spec=["run"])  # oneway_shortest류: 속성 자체가 없음을 흉내
    else:
        instance = MagicMock()
        instance.candidate_feature_vectors = candidate_feature_vectors
    instance.run.return_value = responses
    return MagicMock(return_value=instance)


@pytest.fixture
def graph() -> nx.Graph:
    G = nx.Graph()
    G.add_node(1, lat=37.5, lon=127.0)
    G.add_node(2, lat=37.51, lon=127.01)
    G.add_edge(1, 2, length=1000)
    return G


@pytest.fixture
def auth_service():
    mock = MagicMock()
    mock.check_access_token.return_value = (Status.SUCCESS, None, None)
    return mock


@pytest.fixture
def route_service(graph, auth_service):
    return RouteService(graph, auth_service)


@pytest.fixture
def profile_service(auth_service):
    return LongTermProfileService(auth_service)


@pytest.fixture
def history_store():
    return _FakeRouteHistoryStore()


@pytest.fixture
def preference_store():
    return _FakePreferenceStore()


@pytest.fixture(autouse=True)
def patched_repositories(history_store, preference_store):
    user = MagicMock(id=1)
    patches = [
        patch(
            "src.service.route.route_service.UserRepository.find_by_provider_and_provider_id",
            return_value=user,
        ),
        patch(
            "src.service.route.route_service.RouteHistoryRepository.save",
            side_effect=history_store.save,
        ),
        patch(
            "src.service.route.route_service.RoutePoiRepository.find_near_route",
            return_value=[],
        ),
        patch(
            "src.service.user.longterm_profile_service.UserRepository.find_by_provider_and_provider_id",
            return_value=user,
        ),
        patch(
            "src.service.user.longterm_profile_service.RouteHistoryRepository.find_by_id",
            side_effect=history_store.find_by_id,
        ),
        patch(
            "src.service.user.longterm_profile_service.RouteFeedbackRepository.find_by_route_history_id",
            return_value=None,
        ),
        patch("src.service.user.longterm_profile_service.RouteFeedbackRepository.upsert"),
        patch(
            "src.service.user.longterm_profile_service.UserPreferenceRepository.get_by_user_id",
            side_effect=preference_store.get_by_user_id,
        ),
        patch(
            "src.service.user.longterm_profile_service.UserPreferenceRepository.upsert",
            side_effect=preference_store.upsert,
        ),
        patch(
            "src.agent.nodes.route_executor.UserPreferenceRepository.get_by_user_id",
            side_effect=preference_store.get_by_user_id,
        ),
    ]
    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


def _feedback(safety=4, comfort=5, overall=5) -> RouteFeedbackRequest:
    return RouteFeedbackRequest(rating_safety=safety, rating_comfort=comfort, rating_overall=overall)


def _generate_and_get_history_id(route_service, target_km: float) -> int:
    result = route_service.get_route(
        ACCESS_TOKEN, origin=ORIGIN, target_km=target_km, mode=WalkMode.CIRCULAR_RANDOM,
    )
    assert result[0].status == WalkRouteStatus.SUCCESS
    return result[0].id


class TestCandidateCountDrivesFeedbackOutcome:
    """2026-09-17 로컬 API 실측 id=19(후보 3개)/id=20(후보 1개) 케이스에 대응."""

    def test_후보가_1개면_생성된_경로의_피드백이_insufficient_candidates다(
        self, route_service, profile_service
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(5.19, None)

        history_id = _generate_and_get_history_id(route_service, target_km=5.0)
        result = profile_service.submit_feedback(ACCESS_TOKEN, history_id, _feedback())

        assert result.status == RouteFeedbackStatus.INSUFFICIENT_CANDIDATES

    def test_후보가_3개면_생성된_경로의_피드백이_success이고_가중치가_갱신된다(
        self, route_service, profile_service
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )

        history_id = _generate_and_get_history_id(route_service, target_km=2.5)
        result = profile_service.submit_feedback(
            ACCESS_TOKEN, history_id, _feedback(safety=4, comfort=5, overall=5)
        )

        assert result.status == RouteFeedbackStatus.SUCCESS
        # 대표 후보(candidate_features[0])가 나머지 둘보다 뚜렷하게 편안함 -> X_contrast[comfort] > 0,
        # 별점도 comfort=5로 높으므로 weights_comfort는 반드시 오른다(BASE_COMFORT=0.0에서 시작).
        assert result.weights_comfort > 0.0

    def test_feedback_count는_성공한_피드백마다_1씩_증가한다(
        self, route_service, profile_service, preference_store
    ):
        """id=19 케이스의 'feedback_count: 1 -> 2' 관측과 같은 성질 — 절대값이 아니라
        "매 성공 피드백마다 +1"이 불변식이라는 것을 두 번 연속 호출로 확인한다."""
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )

        first_id = _generate_and_get_history_id(route_service, target_km=2.5)
        first = profile_service.submit_feedback(ACCESS_TOKEN, first_id, _feedback())
        assert first.status == RouteFeedbackStatus.SUCCESS
        assert preference_store.get_by_user_id(1).feedback_count == 1

        second_id = _generate_and_get_history_id(route_service, target_km=2.5)
        second = profile_service.submit_feedback(ACCESS_TOKEN, second_id, _feedback())
        assert second.status == RouteFeedbackStatus.SUCCESS
        assert preference_store.get_by_user_id(1).feedback_count == 2

    def test_후보가_1개인_경로는_피드백을_반복해도_feedback_count가_늘지_않는다(
        self, route_service, profile_service, preference_store
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(5.19, None)

        history_id = _generate_and_get_history_id(route_service, target_km=5.0)
        profile_service.submit_feedback(ACCESS_TOKEN, history_id, _feedback())
        profile_service.submit_feedback(ACCESS_TOKEN, history_id, _feedback())

        assert preference_store.get_by_user_id(1) is None  # UserPreferenceRepository.upsert 자체가 호출되지 않음

    def test_저장된_candidate_features가_엔진이_만든_값과_순서까지_완전히_같다(
        self, route_service, history_store
    ):
        """route_service.get_route()가 RouteHistory에 넘기는 candidate_features가
        engine.candidate_feature_vectors를 값·순서 그대로 옮겼는지 확인한다 — 여기서 한 번이라도
        누락/재정렬/변형이 생기면 대표 후보(index 0)가 뒤바뀌어 X_contrast 자체가 틀어진다."""
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )

        history_id = _generate_and_get_history_id(route_service, target_km=2.5)
        stored = history_store.find_by_id(history_id, user_id=1)

        assert stored.candidate_features == _SUCCESS_CANDIDATE_FEATURES

    def test_각_후보는_자기_id와_자신이_첫번째인_candidate_features를_가진다(
        self, route_service, history_store
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )

        results = route_service.get_route(
            ACCESS_TOKEN, origin=ORIGIN, target_km=2.5, mode=WalkMode.CIRCULAR_RANDOM,
        )

        assert len({result.id for result in results}) == len(results) == 3
        for index, result in enumerate(results):
            stored = history_store.find_by_id(result.id, user_id=1)
            expected = [
                _SUCCESS_CANDIDATE_FEATURES[index],
                *_SUCCESS_CANDIDATE_FEATURES[:index],
                *_SUCCESS_CANDIDATE_FEATURES[index + 1:],
            ]
            assert stored.candidate_features == expected

    def test_같은_경로_피드백_재제출은_별점만_갱신하고_프로필은_중복_학습하지_않는다(
        self, route_service, profile_service, preference_store
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )
        history_id = _generate_and_get_history_id(route_service, target_km=2.5)
        feedback_lookup = longterm_profile_module.RouteFeedbackRepository.find_by_route_history_id
        feedback_lookup.side_effect = [None, MagicMock()]

        first = profile_service.submit_feedback(ACCESS_TOKEN, history_id, _feedback())
        first_safety = first.weights_safety
        first_comfort = first.weights_comfort
        second = profile_service.submit_feedback(
            ACCESS_TOKEN, history_id, _feedback(safety=1, comfort=1, overall=1)
        )

        assert preference_store.get_by_user_id(1).feedback_count == 1
        assert second.weights_safety == first_safety
        assert second.weights_comfort == first_comfort

    def test_피드백_시점_SGD_입력에_생성_시점_candidate_features가_그대로_전달된다(
        self, route_service, profile_service
    ):
        """저장된 값이 아니라 실제로 _contrast_vector()에 들어가는 인자 자체를 가로채,
        중간에 값이 바뀌거나 다른 route_history의 값과 뒤섞이지 않는지 확인한다."""
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )
        history_id = _generate_and_get_history_id(route_service, target_km=2.5)

        with patch.object(
            longterm_profile_module, "_contrast_vector",
            wraps=longterm_profile_module._contrast_vector,
        ) as contrast_spy:
            result = profile_service.submit_feedback(ACCESS_TOKEN, history_id, _feedback())

        contrast_spy.assert_called_once_with(_SUCCESS_CANDIDATE_FEATURES)
        assert result.status == RouteFeedbackStatus.SUCCESS

    def test_SGD_결과값이_생성_시점_특성값으로_계산한_기대치와_정확히_일치한다(
        self, route_service, profile_service
    ):
        """방향(오르내림)만이 아니라 실제 숫자가 candidate_features로부터 정확히 계산됐는지
        확인한다. 기대값은 _contrast_vector/_adaptive_learning_rate 등 이미 별도로 검증된
        순수 함수를 그대로 이어붙여 계산했다(2026-09-17 로컬 API 실측에서 확인한 것과 같은
        '초기 가중치(safety=0.5, comfort=0.0)에서 feedback_count=0으로 첫 피드백을 받는' 조건).

        #487 반영: 편안 대조값(+0.525)은 상한(±0.1)으로 제한돼 0.1로 계산되고, 안전은 상한 이내(-0.035)라
        SGD 계산값이 0.4864로 나오지만 설문을 하지 않은 사용자의 하한(기본값 safety=0.5)에 걸려 0.5가 된다.
        상한·하한이 없던 때의 값은 safety=0.48701998832031257, comfort=0.25573142519531245였다.
        """
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )
        history_id = _generate_and_get_history_id(route_service, target_km=2.5)

        result = profile_service.submit_feedback(
            ACCESS_TOKEN, history_id, _feedback(safety=4, comfort=5, overall=5)
        )

        assert result.status == RouteFeedbackStatus.SUCCESS
        assert result.weights_safety == pytest.approx(0.5)
        assert result.weights_comfort == pytest.approx(0.05037090390625)

    @pytest.mark.parametrize(
        "selected_tags, initial_safety, initial_comfort",
        [
            (["안전한 길", "편안한 길"], 0.65, 0.15),  # 현재 앱 표현
            (["안전", "편안"], 0.65, 0.15),  # 기존 서버 표현
            (["안전한 길"], 0.5 + 0.8 / 3, 0.3 / 9),
            (["편안한 길"], 0.5 + 0.3 / 9, 0.8 / 3),
        ],
    )
    def test_온보딩_초기값_하한은_앱이_보낸_표현으로_저장된_태그에서도_적용된다(
        self, route_service, profile_service, preference_store,
        selected_tags, initial_safety, initial_comfort,
    ):
        """selected_tags에는 제출한 표현("안전한 길")이 그대로 저장된다. 하한(온보딩 초기값)이 저장된 원본
        태그를 "안전" 문자열로만 찾으면 앱 표현을 "둘 다 미선택"(0.533/0.033)으로 오인해 실제 초기값보다
        낮은 하한을 쓰게 된다. 대표 후보가 덜 안전한 음의 대조 + 안전 5점은 안전 가중치를 내리는 갱신이라,
        하한이 올바르면 갱신 결과가 초기값에서 멈춘다."""
        preference_store._row = MagicMock(
            user_id=1, survey_completed=True, selected_tags=selected_tags,
            weights_safety=initial_safety, weights_comfort=initial_comfort, feedback_count=0,
        )
        features = [
            {"safety": 0.5, "comfort": 0.9},
            {"safety": 0.8, "comfort": 0.9},
            {"safety": 0.8, "comfort": 0.9},
        ]  # 안전 대조 -0.3(상한으로 -0.1), 편안 대조 0
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(2.47, features)
        history_id = _generate_and_get_history_id(route_service, target_km=2.5)

        result = profile_service.submit_feedback(
            ACCESS_TOKEN, history_id, _feedback(safety=5, comfort=3, overall=5)
        )

        assert result.status == RouteFeedbackStatus.SUCCESS
        assert result.weights_safety == pytest.approx(initial_safety)
        assert result.weights_comfort == pytest.approx(initial_comfort)

    def test_엔진_클래스와_무관하게_candidate_feature_vectors만_있으면_계약이_성립한다(
        self, route_service, profile_service
    ):
        """route_service.py는 engine.candidate_feature_vectors를 duck-typing으로 읽으므로
        (getattr(engine, "candidate_feature_vectors", None)), base_engines에 어떤 엔진
        클래스가 매핑돼 있는지는 이 계약과 무관하다 — 이름조차 CircularBeamEngine/
        CircularGraspWaypointAlnsEngine이 아닌 임의의 스텁으로도 동일하게 동작해야 한다."""
        class _NotAProductionEngineClass:
            def __init__(self, *args, **kwargs):
                self.candidate_feature_vectors = _SUCCESS_CANDIDATE_FEATURES

            def run(self):
                return [
                    WalkRouteResponse(
                        status=WalkRouteStatus.SUCCESS,
                        mode=WalkMode.CIRCULAR_RANDOM,
                        coordinates=[[37.5, 127.0], [37.51, 127.01], [37.5, 127.0]],
                        total_km=2.47,
                    )
                    for _ in _SUCCESS_CANDIDATE_FEATURES
                ]

        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _NotAProductionEngineClass

        history_id = _generate_and_get_history_id(route_service, target_km=2.5)
        result = profile_service.submit_feedback(ACCESS_TOKEN, history_id, _feedback())

        assert result.status == RouteFeedbackStatus.SUCCESS


# ── 실제 CircularGraspWaypointAlnsEngine으로 검증(스텁이 아니라 진짜 순환 엔진) ──────
#
# route_service.base_engines에는 아직 연결돼 있지 않다(엔진 매핑은 별도 작업 대상 — PR 메모
# 참고). 게다가 CircularGraspWaypointAlnsEngine.__init__은 custom_weights/profile 키워드를
# 받지 않아 route_service._build_engine()의 CIRCULAR_RANDOM 호출부
# (`self.base_engines[mode](inp, self.G, custom_weights=custom_weights, profile=profile)`,
# route_service.py:310)와 시그니처 자체가 안 맞는다 — base_engines 딕셔너리만 바꿔서는
# TypeError가 난다(엔진 매핑 작업에 어댑터/시그니처 조정도 함께 필요하다는 뜻이라, 이것도
# PR 메모에 남긴다). 그래서 여기서는 RouteService.get_route()를 거치지 않고, 엔진의 실제
# run() 출력을 RouteHistoryRepository.save()가 받는 것과 같은 형태로 직접 이어붙여 "GRASP+ALNS가
# 실제로 만든 candidate_feature_vectors가 feedback까지 살아남는지"를 검증한다.

_GRID = 7
_LAT_STEP = 0.0015   # 약 167m/step
_LON_STEP = 0.0018   # 약 160m/step (37.5도 위도 기준)
_ORIGIN_LAT, _ORIGIN_LON = 37.5000, 127.0000


def _grid_coords(row: int, col: int) -> tuple[float, float]:
    return _ORIGIN_LAT + row * _LAT_STEP, _ORIGIN_LON + col * _LON_STEP


@pytest.fixture
def grasp_alns_grid_graph() -> nx.Graph:
    """7x7 격자(실제 위경도 간격, Haversine length) — test_waypoint_engine_assembly.py::
    grid_graph와 같은 방식이다. 이 파일은 자체 fixture를 두는 저장소 관례를 따른다."""
    G = nx.Graph()
    for row in range(_GRID):
        for col in range(_GRID):
            lat, lon = _grid_coords(row, col)
            G.add_node(row * _GRID + col + 1, lat=lat, lon=lon)
    for row in range(_GRID):
        for col in range(_GRID):
            n = row * _GRID + col + 1
            for dr, dc in ((0, 1), (1, 0)):
                r2, c2 = row + dr, col + dc
                if r2 >= _GRID or c2 >= _GRID:
                    continue
                lat1, lon1 = _grid_coords(row, col)
                lat2, lon2 = _grid_coords(r2, c2)
                G.add_edge(n, r2 * _GRID + c2 + 1,
                           length=PathUtils._haversine_m(lat1, lon1, lat2, lon2))
    return G


def _grasp_alns_engine(graph: nx.Graph) -> CircularGraspWaypointAlnsEngine:
    lat, lon = _grid_coords(_GRID // 2, _GRID // 2)
    inp = CircularRouteInput(start_lat=lat, start_lon=lon, target_km=1.2)
    return CircularGraspWaypointAlnsEngine(inp=inp, G=graph)


class TestRealGraspAlnsEngineFeedsIntoFeedback:
    """스텁이 아니라 실제 CircularGraspWaypointAlnsEngine을 돌려, 그 출력이
    longterm_profile_service까지 올바르게 이어지는지 확인한다."""

    def test_후보_개수가_MIN_CANDIDATES_FOR_PROFILE과_정확히_맞는다(self, grasp_alns_grid_graph):
        """MULTI_CANDIDATE_COMBOS 소속인 grasp+alns는 CANDIDATE_COUNT(=3)개를 반환하는데,
        route_service.MIN_CANDIDATES_FOR_PROFILE도 3이다 — 두 상수가 서로 다른 파일에 따로
        있으므로 실제 실행 결과로 항상 일치하는지 고정해둔다(하나만 바뀌면 이 테스트가 깨진다)."""
        engine = _grasp_alns_engine(grasp_alns_grid_graph)

        responses = engine.run()

        assert responses[0].status == WalkRouteStatus.SUCCESS
        assert len(responses) == CANDIDATE_COUNT
        assert len(engine.candidate_feature_vectors) == len(responses) == MIN_CANDIDATES_FOR_PROFILE

    def test_실제_엔진이_만든_candidate_features로_피드백_처리까지_성공한다(
        self, grasp_alns_grid_graph, profile_service, history_store
    ):
        engine = _grasp_alns_engine(grasp_alns_grid_graph)
        responses = engine.run()
        assert responses[0].status == WalkRouteStatus.SUCCESS
        assert len(engine.candidate_feature_vectors) >= MIN_CANDIDATES_FOR_PROFILE

        # RouteService.get_route()가 성공 시 하는 영속화 단계를 그대로 재현한다(위 모듈
        # docstring 설명대로 route_service.get_route()는 아직 이 엔진과 시그니처가 안 맞아
        # 그대로 거칠 수 없다).
        history = history_store.save(
            user_id=1, mode=WalkMode.CIRCULAR_RANDOM,
            origin_lat=engine.inp.start_lat, origin_lon=engine.inp.start_lon,
            coordinates=responses[0].coordinates, total_km=responses[0].total_km,
            candidate_features=engine.candidate_feature_vectors,
        )

        result = profile_service.submit_feedback(ACCESS_TOKEN, history.id, _feedback())

        assert result.status == RouteFeedbackStatus.SUCCESS


# ── prewalk_router 경로(RouteTool.circular_random_route)로도 같은 계약이 성립하는지 ──────
#
# walk_router(interfaces/api/walk_router.py)는 RouteService.get_route()를 직접 부르지만,
# 실제 앱과 연결되는 prewalk_router는 prewalk_service.py -> route_executor.py(RouteExecutor)
# -> route_tools.py(RouteTool.circular_random_route)를 거쳐서야 RouteService.get_route()에
# 도달한다(2026-09-18 코드 조사로 확인, refactor/#458 이슈 배경). RouteTool.circular_random_route는
# asyncio.to_thread로 RouteService.get_route를 그대로 호출하므로, walk_router와 같은
# candidate_features 계약이 이 경로로도 성립하는지 직접 검증한다.
#
# StructuredTool/langchain_core는 이 테스트 환경(tests/conftest.py)에서 통째로 mock 처리돼
# 있어(설치돼 있지 않은 외부 패키지) tool_map[...].ainvoke()의 실제 도구 바인딩까지는 재현할
# 수 없다 — 그래서 RouteTool.__init__(get_route_service()/GpsArtService 등 DI 의존)은
# 건너뛰고, prewalk_router가 실제로 실행하는 코드인 circular_random_route() 코루틴 자체를
# 직접 호출한다(RouteExecutor.run()의 가중치 조립 로직은 test_routue_service.py::
# TestRouteWeightPersonalization이 이미 별도로 검증하므로 여기서 반복하지 않는다).


def _real_route_tool(route_service: RouteService) -> RouteTool:
    tool = RouteTool.__new__(RouteTool)  # __init__의 get_route_service()/GpsArtService 의존 회피
    tool.route_service = route_service
    return tool


class TestPrewalkPathReachesCandidateFeaturesContract:
    """prewalk_router가 실제로 호출하는 RouteTool.circular_random_route를 통해서도
    walk_router(RouteService.get_route 직접 호출)와 동일한 candidate_features 계약이
    성립하는지 확인한다."""

    def test_prewalk_경로로도_candidate_features가_정상_저장되고_피드백까지_이어진다(
        self, route_service, profile_service, history_store
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )
        tool = _real_route_tool(route_service)

        result = asyncio.run(tool.circular_random_route(
            origin=ORIGIN, target_km=2.5, access_token=ACCESS_TOKEN,
        ))

        assert result[0].status == WalkRouteStatus.SUCCESS
        stored = history_store.find_by_id(result[0].id, user_id=1)
        assert stored.candidate_features == _SUCCESS_CANDIDATE_FEATURES

        feedback_result = profile_service.submit_feedback(ACCESS_TOKEN, result[0].id, _feedback())
        assert feedback_result.status == RouteFeedbackStatus.SUCCESS

    def test_후보가_1개면_prewalk_경로로_생성해도_insufficient_candidates다(
        self, route_service, profile_service
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(5.19, None)
        tool = _real_route_tool(route_service)

        result = asyncio.run(tool.circular_random_route(
            origin=ORIGIN, target_km=5.0, access_token=ACCESS_TOKEN,
        ))

        feedback_result = profile_service.submit_feedback(ACCESS_TOKEN, result[0].id, _feedback())
        assert feedback_result.status == RouteFeedbackStatus.INSUFFICIENT_CANDIDATES

    def test_walk_router와_prewalk_router_경로가_같은_결과를_낸다(
        self, route_service
    ):
        """walk_router(RouteService.get_route 직접 호출)와 prewalk_router
        (RouteTool.circular_random_route 경유)가 서로 다른 코드 경로를 타지만 같은
        RouteService 계약에 도달한다는 것을 나란히 확인한다."""
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )

        walk_router_result = route_service.get_route(
            ACCESS_TOKEN, origin=ORIGIN, target_km=2.5, mode=WalkMode.CIRCULAR_RANDOM,
        )
        tool = _real_route_tool(route_service)
        prewalk_router_result = asyncio.run(tool.circular_random_route(
            origin=ORIGIN, target_km=2.5, access_token=ACCESS_TOKEN,
        ))

        assert walk_router_result[0].status == prewalk_router_result[0].status == WalkRouteStatus.SUCCESS
        assert walk_router_result[0].total_km == prewalk_router_result[0].total_km


# ── RouteExecutor.run()까지 포함해서 검증(가중치 조립 로직까지 실제 코드로) ─────────────
#
# 위 TestPrewalkPathReachesCandidateFeaturesContract는 RouteTool.circular_random_route를
# 직접 호출해 그 아래(RouteService)만 검증했다. 여기서는 한 겹 더 올라가 RouteExecutor.run()
# 자체(모드 판별 -> UserPreference 기반 가중치 조립 -> tool_map 조회 -> 호출)까지 실제 코드로
# 실행한다. PrewalkOrchestrator(LangGraph 상태머신)와 StructuredTool 바인딩은 여전히 이 테스트
# 환경(langgraph 미설치, tests/conftest.py가 전체 mock 처리)에서는 재현할 수 없어 제외한다 —
# RouteExecutor.__init__의 DI(get_gps_art_service/get_route_service)도 같은 이유로 우회하고,
# tool_map은 StructuredTool.ainvoke(dict)와 같은 인터페이스(_DirectInvoke)로 직접 구성한다.


class _DirectInvoke:
    """StructuredTool.ainvoke(dict)를 흉내: dict를 그대로 kwargs로 풀어 코루틴 함수를 부른다."""

    def __init__(self, coroutine_fn):
        self._fn = coroutine_fn

    async def ainvoke(self, args: dict):
        return await self._fn(**args)


def _real_route_executor(route_service: RouteService) -> RouteExecutor:
    executor = RouteExecutor.__new__(RouteExecutor)  # __init__의 DI 의존(get_gps_art_service 등) 회피
    tool = _real_route_tool(route_service)
    tool.tool_map = {name: _DirectInvoke(getattr(tool, name)) for name in MODE_TOOL_MAP.values()}
    executor.route_tool = tool
    return executor


def _circular_state(target_km: float = 2.5) -> State:
    return State(
        user_id=1,
        current_location=Location(lat=ORIGIN.lat, lon=ORIGIN.lon),
        access_token=ACCESS_TOKEN,
        mode=WalkMode.CIRCULAR_RANDOM,
        user_context=CircularPreference(
            origin=Location(lat=ORIGIN.lat, lon=ORIGIN.lon), target_km=target_km,
        ),
    )


class TestRouteExecutorReachesCandidateFeaturesContract:
    """prewalk_router가 실제로 실행하는 RouteExecutor.run()까지(가중치 조립 포함) 실제
    코드로 태워 candidate_features 계약이 성립하는지 확인한다."""

    def test_RouteExecutor_run을_거쳐도_candidate_features가_정상_저장되고_피드백까지_이어진다(
        self, route_service, profile_service, history_store
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(
            2.47, _SUCCESS_CANDIDATE_FEATURES
        )
        executor = _real_route_executor(route_service)

        result_state = asyncio.run(executor.run(_circular_state()))

        assert result_state.route_result is not None
        assert result_state.route_result[0].status == WalkRouteStatus.SUCCESS
        stored = history_store.find_by_id(result_state.route_result[0].id, user_id=1)
        assert stored.candidate_features == _SUCCESS_CANDIDATE_FEATURES

        feedback_result = profile_service.submit_feedback(
            ACCESS_TOKEN, result_state.route_result[0].id, _feedback()
        )
        assert feedback_result.status == RouteFeedbackStatus.SUCCESS

    def test_후보가_1개면_RouteExecutor_run_경로로도_insufficient_candidates다(
        self, route_service, profile_service
    ):
        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _engine_stub(5.19, None)
        executor = _real_route_executor(route_service)

        result_state = asyncio.run(executor.run(_circular_state(target_km=5.0)))

        feedback_result = profile_service.submit_feedback(
            ACCESS_TOKEN, result_state.route_result[0].id, _feedback()
        )
        assert feedback_result.status == RouteFeedbackStatus.INSUFFICIENT_CANDIDATES

    def test_UserPreference_기반_가중치_조립이_실제로_route_service까지_전달된다(
        self, route_service
    ):
        """RouteExecutor.run()이 UserPreferenceRepository에서 조회한 안전/편안 가중치를
        실제로 route_service.get_route까지 흘려보내는지 확인한다 — RouteTool을 직접 부르는
        위 클래스(가중치 조립을 건너뜀)와 이 클래스를 가르는 지점이다.

        get_route() 호출 인자를 잡아낸다(엔진 생성자가 아니라) — CircularGraspWaypointAlnsEngine은
        custom_weights 인자를 받지 않으므로(선호는 #462에서 cost_context로 따로 전달하게 됐다)
        엔진 생성자에서 잡으면 항상 None이 된다."""
        class _StubEngine:
            # route_service가 CIRCULAR_RANDOM 분기에서 cost_context를 넘기므로(#462) 실제
            # 엔진과 같은 시그니처를 유지한다 — 안 받으면 TypeError로 조용히 실패한다.
            def __init__(self, inp, G, cost_context=None):
                self.candidate_feature_vectors = _SUCCESS_CANDIDATE_FEATURES

            def run(self):
                return [
                    WalkRouteResponse(
                        status=WalkRouteStatus.SUCCESS, mode=WalkMode.CIRCULAR_RANDOM,
                        coordinates=[[37.5, 127.0], [37.51, 127.01], [37.5, 127.0]],
                        total_km=2.47,
                    )
                    for _ in _SUCCESS_CANDIDATE_FEATURES
                ]

        route_service.base_engines[WalkMode.CIRCULAR_RANDOM] = _StubEngine
        executor = _real_route_executor(route_service)

        with patch(
            "src.agent.nodes.route_executor.UserPreferenceRepository.get_by_user_id",
            return_value=MagicMock(weights_safety=0.9, weights_comfort=0.1),
        ), patch.object(
            route_service, "get_route", wraps=route_service.get_route,
        ) as get_route_spy:
            asyncio.run(executor.run(_circular_state()))

        custom_weights = get_route_spy.call_args.args[5]
        assert custom_weights.safety == pytest.approx(0.9)
        assert custom_weights.comfort == pytest.approx(0.1)
