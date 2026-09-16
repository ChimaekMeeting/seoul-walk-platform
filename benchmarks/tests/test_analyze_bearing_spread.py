"""benchmarks/tests/test_analyze_bearing_spread.py

전역 배치 판정에 쓰는 순수 기하 함수만 검증한다. 집계·러너는 일회성 산출물이라
회귀 대상이 아니다.
"""

import pytest

from benchmarks.analyze_bearing_spread import (
    ideal_span_deg,
    parse_bearings,
    sign_reversals,
    signed_turns_deg,
)
from benchmarks.measure_pool_geometry import circular_span_deg


def test_one_way_rotation_has_no_reversal():
    # 한 방향으로 계속 도는 배치 — 원형 배치의 정상 형태
    assert sign_reversals(signed_turns_deg([0.0, 36.0, 72.0, 108.0])) == 0


def test_return_to_previous_bearing_is_detected():
    # +90 뒤 -90으로 되돌아오는 배치. |cos| 항은 두 단계 모두 페널티 0을 준다.
    assert sign_reversals(signed_turns_deg([0.0, 90.0, 0.0])) == 1


def test_zero_turn_does_not_break_the_sign_run():
    # 같은 방위로 한 번 머무는 것은 방향 전환이 아니다
    assert sign_reversals([10.0, 0.0, 10.0]) == 0


def test_turns_wrap_across_north():
    # 350도 -> 10도는 +20도이지 -340도가 아니다
    assert signed_turns_deg([350.0, 10.0]) == pytest.approx([20.0])


def test_circular_span_ignores_the_largest_gap():
    assert circular_span_deg([350.0, 10.0, 30.0]) == pytest.approx(40.0)


def test_circular_span_of_single_bearing_is_zero():
    assert circular_span_deg([12.5]) == 0.0


def test_ideal_span_matches_inscribed_angle():
    # N=4: (4-1)*180/5 = 108도. 원주각 성질상 360도가 아니다.
    assert ideal_span_deg(4) == pytest.approx(108.0)
    assert ideal_span_deg(2) == pytest.approx(60.0)


def test_parse_rejects_single_waypoint_and_garbage():
    assert parse_bearings("[12.5]") is None
    assert parse_bearings("") is None
    assert parse_bearings(None) is None
    assert parse_bearings("not json") is None


def test_parse_folds_into_0_360():
    assert parse_bearings("[-90.0, 370.0]") == pytest.approx([270.0, 10.0])
