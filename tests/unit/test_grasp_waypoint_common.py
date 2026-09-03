from src.route_engine.engines.grasp_waypoint_common import is_degenerate_loop_route


def test_simple_round_trip_now_caught_by_new_threshold():
    # 단순 왕복(새 정의 기준 repeated_edge_ratio=0.5)은 이전 0.50 임계값으로는
    # 놓쳤지만(0.5 > 0.50이 False), 새 0.35 임계값에서는 잡혀야 한다(0.5 > 0.35).
    assert is_degenerate_loop_route(0.5, 1000.0, 3000.0, 0.9) is True


def test_repeated_edge_ratio_boundary():
    assert is_degenerate_loop_route(0.35, None, 3000.0, None) is False   # 경계값 포함 안 됨
    assert is_degenerate_loop_route(0.351, None, 3000.0, None) is True


def test_waypoint_separation_boundary():
    target_m = 3000.0
    assert is_degenerate_loop_route(0.0, target_m * 0.20, target_m, None) is False
    assert is_degenerate_loop_route(0.0, target_m * 0.20 - 1, target_m, None) is True


def test_segment_balance_boundary():
    assert is_degenerate_loop_route(0.0, None, 3000.0, 0.25) is False
    assert is_degenerate_loop_route(0.0, None, 3000.0, 0.249) is True


def test_none_values_skip_their_condition():
    assert is_degenerate_loop_route(0.0, None, 3000.0, None) is False
