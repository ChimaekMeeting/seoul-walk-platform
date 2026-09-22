"""
tests/unit/test_interviewer_shortest_conflict.py

Interviewer._update_shortest_km()/_is_oneway_shortest_conflict()을 검증한다.

- _update_shortest_km(state): oneway_shortest·oneway_random 두 모드 모두에서 위치가
  확정되면 state.shortest_km을 채우고, 그 외에는 None으로 지운다(stale 방지).
  - oneway_shortest는 route_tool.tool_map["oneway_shortest_route"]를 통해 최종 경로를
    직접 생성한다(POI·RouteHistory까지 포함, route_executor와 같은 타임아웃 보호 경로) —
    state.route_result도 같이 채운다(이 결과가 곧 최종 경로라서).
  - oneway_random은 route_service.get_shortest_km(가벼운 A*만, Optional[float])으로
    참고용 거리만 얻는다 — 최종 경로는 GRASP+ALNS로 따로 생성되므로 state.route_result는
    채우지 않고 항상 None으로 지운다.
- _is_oneway_shortest_conflict(state): oneway_random에서 목표 거리가 state.shortest_km
  이하면(우회할 여지가 없는 요청) True.

route_service.get_shortest_km/route_tool을 mock해 실제 그래프·A*·DB 없이 결정론적으로
확인한다(scripts/eval_interviewer.py는 이 판단 이후 실제로 생성되는 안내 문구의 품질을
실제 OpenAI 호출로 따로 검증한다 — 이 파일의 범위가 아니다).
"""
import asyncio
import sys
import importlib
from unittest.mock import AsyncMock, MagicMock

# conftest.py가 gpt_client·interviewer를 통째로 MagicMock으로 치환해 둔다(대부분의
# 테스트는 LLM을 실제로 안 쓰니 괜찮지만, 이 파일은 Interviewer의 실제 판단 로직을
# 그대로 실행해야 해서 test_weight_extractor_state.py와 같은 방식으로 원본을 다시 불러온다.
sys.modules.pop("src.infrastructure.external.client.gpt_client", None)
sys.modules.pop("src.agent.nodes.interviewer", None)
importlib.import_module("src.infrastructure.external.client.gpt_client")
Interviewer = importlib.import_module("src.agent.nodes.interviewer").Interviewer

from src.schema.prewalk_schema import (
    State,
    Location,
    CircularPreference,
    OnewayPreference,
    OnewayShortestPreference,
)
from src.interfaces.schema.walk_schema import WalkMode, WalkRouteResponse, WalkRouteStatus

_CURRENT_LOCATION = Location(lat=37.5, lon=127.0, address="현재 위치 주소", place_name="현재 위치")
_FULL      = Location(lat=37.5, lon=127.0, address="테스트 주소", place_name="테스트 장소")
_NO_COORD  = Location(place_name="좌표 미확정 장소")  # lat/lon 없음 — 아직 Kakao 검색 전


def _shortest_route_results(shortest_km):
    """route_tool의 oneway_shortest_route가 돌려주는 List[WalkRouteResponse]를 흉내 낸다.
    shortest_km이 None이면 A*가 경로를 못 찾은 경우(NO_PATH)를 흉내 낸다."""
    if shortest_km is None:
        return [WalkRouteResponse(
            status=WalkRouteStatus.NO_PATH, mode=WalkMode.ONEWAY_SHORTEST, coordinates=[], total_km=0.0,
        )]
    return [WalkRouteResponse(
        status=WalkRouteStatus.SUCCESS, mode=WalkMode.ONEWAY_SHORTEST,
        coordinates=[[127.0, 37.5]], total_km=shortest_km,
    )]


def _make_interviewer(shortest_km):
    """route_service.get_shortest_km(oneway_random용, Optional[float])과 route_tool의
    oneway_shortest_route(oneway_shortest용, List[WalkRouteResponse])가 둘 다 같은 고정
    거리를 반환하도록 mock한 Interviewer를 만든다.
    """
    route_service = MagicMock()
    route_service.get_shortest_km.return_value = shortest_km

    oneway_shortest_tool = MagicMock()
    oneway_shortest_tool.ainvoke = AsyncMock(return_value=_shortest_route_results(shortest_km))

    iv = Interviewer(route_service=route_service)
    iv.route_tool = MagicMock()
    iv.route_tool.tool_map = {"oneway_shortest_route": oneway_shortest_tool}
    return iv, route_service


def _state(pref) -> State:
    return State(user_id=1, current_location=_CURRENT_LOCATION, user_context=pref)


def _update_shortest_km(iv, state):
    asyncio.run(iv._update_shortest_km(state))


def test_target_km_below_shortest_is_conflict():
    iv, _ = _make_interviewer(shortest_km=1.0)
    state = _state(OnewayPreference(origin=_FULL, destination=_FULL, target_km=0.5))
    _update_shortest_km(iv, state)
    assert state.shortest_km == 1.0
    assert state.route_result is None  # oneway_random은 참고용 숫자만, route_result는 안 채움
    assert iv._is_oneway_shortest_conflict(state) is True


def test_target_km_equal_to_shortest_is_conflict():
    """경계값 — 우회할 여지가 전혀 없는 '딱 그만큼'도 충돌로 본다(<=)."""
    iv, _ = _make_interviewer(shortest_km=2.0)
    state = _state(OnewayPreference(origin=_FULL, destination=_FULL, target_km=2.0))
    _update_shortest_km(iv, state)
    assert state.shortest_km == 2.0
    assert iv._is_oneway_shortest_conflict(state) is True


def test_target_km_above_shortest_is_not_conflict():
    iv, _ = _make_interviewer(shortest_km=1.0)
    state = _state(OnewayPreference(origin=_FULL, destination=_FULL, target_km=2.0))
    _update_shortest_km(iv, state)
    assert state.shortest_km == 1.0  # 필드는 여전히 채워짐(참고용) — 다만 충돌은 아님
    assert iv._is_oneway_shortest_conflict(state) is False


def test_oneway_shortest_mode_populates_field_but_never_conflicts():
    """oneway_shortest는 target_km 필드 자체가 없어 '충돌' 개념이 없지만, 참고용
    최단거리는 똑같이 state.shortest_km에 채워져야 한다(2026-09-21). oneway_shortest는
    이 결과가 곧 최종 경로라 route_tool(oneway_shortest_route)을 통해 state.route_result도
    같이 채워진다(2026-09-23 후속2) — route_service.get_shortest_km은 이 모드에선 안 쓴다."""
    iv, rs = _make_interviewer(shortest_km=3.4)
    state = _state(OnewayShortestPreference(origin=_FULL, destination=_FULL))
    _update_shortest_km(iv, state)
    assert state.shortest_km == 3.4
    assert state.route_result is not None
    assert state.route_result[0].status == WalkRouteStatus.SUCCESS
    iv.route_tool.tool_map["oneway_shortest_route"].ainvoke.assert_awaited_once()
    rs.get_shortest_km.assert_not_called()
    assert iv._is_oneway_shortest_conflict(state) is False


def test_circular_mode_clears_field_and_never_conflicts():
    """순환 모드는 애초에 이 판단 대상이 아니다 — 불필요한 A* 호출도, 이전 값 잔존도 없어야 한다."""
    iv, rs = _make_interviewer(shortest_km=1.0)
    state = _state(CircularPreference(origin=_FULL, target_km=0.1))
    state.shortest_km = 9.9  # 이전 턴(다른 모드)에서 남아있었을 수 있는 값 — 지워져야 함
    _update_shortest_km(iv, state)
    assert state.shortest_km is None
    assert state.route_result is None
    rs.get_shortest_km.assert_not_called()
    iv.route_tool.tool_map["oneway_shortest_route"].ainvoke.assert_not_awaited()
    assert iv._is_oneway_shortest_conflict(state) is False


def test_missing_target_km_still_populates_field_but_not_conflict():
    """거리를 아직 안 정했어도 위치만 확정됐으면 참고용 최단거리는 채운다 — 다만 비교할
    target_km이 없으니 충돌 판정은 못 한다(_get_missing_info가 따로 target_km을 재질문)."""
    iv, rs = _make_interviewer(shortest_km=1.0)
    state = _state(OnewayPreference(origin=_FULL, destination=_FULL, target_km=None))
    _update_shortest_km(iv, state)
    assert state.shortest_km == 1.0
    rs.get_shortest_km.assert_called_once()
    assert iv._is_oneway_shortest_conflict(state) is False


def test_unresolved_location_clears_field_and_skips_astar_call():
    """origin/destination 좌표가 아직 안 정해졌으면 A*를 호출하지 않고 필드도 비운다."""
    iv, rs = _make_interviewer(shortest_km=1.0)
    state = _state(OnewayPreference(origin=_NO_COORD, destination=_FULL, target_km=0.5))
    _update_shortest_km(iv, state)
    assert state.shortest_km is None
    assert state.route_result is None
    rs.get_shortest_km.assert_not_called()
    iv.route_tool.tool_map["oneway_shortest_route"].ainvoke.assert_not_awaited()
    assert iv._is_oneway_shortest_conflict(state) is False


def test_no_path_from_engine_leaves_field_none_and_not_a_conflict():
    """A*가 경로를 못 찾으면(get_shortest_km=None) 필드도 None, 충돌 여부도 판단 못 한다."""
    iv, _ = _make_interviewer(shortest_km=None)
    state = _state(OnewayPreference(origin=_FULL, destination=_FULL, target_km=0.5))
    _update_shortest_km(iv, state)
    assert state.shortest_km is None
    assert state.route_result is None
    assert iv._is_oneway_shortest_conflict(state) is False
