"""
benchmarks/tests/test_density_stratified_runner.py

밀도 층화 러너의 실행 전 안전장치 검증(2026-09-14, 이슈 #427 튜닝값 반영 후 부분 재실행).

이 러너의 산출물은 한 번 돌리는 데 수십 분이 들고, 과거 실행분이 "GRASP-Waypoint+VNS
제외" 같은 판단의 유일한 근거로 남는다. 그래서 여기서 지키는 것은 수치가 아니라 두 가지
사고다 — 오타 난 --algos로 빈 격자를 돌려놓고 결과를 기다리는 것, 그리고 기존 CSV를
말없이 덮어써 근거를 잃는 것.
"""

import pytest

from benchmarks import run_density_stratified_scenarios as runner
from benchmarks.benchmark import SEED_SENSITIVE_SOLVERS
from benchmarks.config import BENCHMARK_SEEDS
from benchmarks.solvers.beam_waypoint_refinement_solver import _DEFAULT_BEAM_WIDTH
from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG


def test_algos_defaults_to_the_full_grid():
    assert runner._parse_algos(None) == runner.ALGOS


def test_algos_subset_keeps_registry_order_not_input_order():
    """CSV의 행 순서가 --algos에 적은 순서에 따라 달라지면 실행분끼리 비교가 번거로워진다."""
    assert runner._parse_algos("beam-wp-vns,grasp-wp-alns") == ["grasp-wp-alns", "beam-wp-vns"]


def test_unknown_algo_stops_before_the_run():
    with pytest.raises(SystemExit) as excinfo:
        runner._parse_algos("grasp-wp-alsn")
    assert "grasp-wp-alsn" in str(excinfo.value)


def test_seed_plan_honours_the_algo_subset():
    subset = ["grasp-wp-alns", "beam-wp-vns"]
    stage1 = runner._seed_plan("1", subset)
    assert stage1 == [(algo, BENCHMARK_SEEDS[0]) for algo in subset]

    stage2 = runner._seed_plan("2", subset)
    assert len(stage2) == len(subset) * len(BENCHMARK_SEEDS)
    assert all(algo in SEED_SENSITIVE_SOLVERS for algo, _ in stage2)


def test_seed_plan_still_runs_seed_insensitive_solvers_once():
    assert runner._seed_plan("2", ["beam-wp"]) == [("beam-wp", None)]


def test_existing_output_stops_the_run(tmp_path):
    out = tmp_path / "results.csv"
    out.write_text("이미 있는 결과", encoding="utf-8")
    with pytest.raises(SystemExit):
        runner._check_output_path(str(out), force=False)


def test_existing_output_is_overwritable_only_on_purpose(tmp_path):
    out = tmp_path / "results.csv"
    out.write_text("이미 있는 결과", encoding="utf-8")
    runner._check_output_path(str(out), force=True)
    runner._check_output_path(str(tmp_path / "new.csv"), force=False)


def test_tuned_knob_that_equals_the_engine_default_stays_visible():
    """beam-wp-alns의 beam_width=8은 튜닝으로 확정된 값이지만 솔버 기본값과 같다 —
    즉 노브 없이 돈 과거 실행분과 동작이 같아서 재실행 대상이 아니다. 이 등식이 깨지면
    (기본값이 바뀌거나 튜닝값이 바뀌면) 재사용 판단도 같이 무너지므로 고정해둔다."""
    assert runner.TUNED_KNOBS["beam-wp-alns"]["beam_width"] == _DEFAULT_BEAM_WIDTH


def test_grasp_alns_knobs_actually_differ_from_engine_defaults():
    """반대로 grasp-wp-alns의 구축 노브 2종은 기본값과 달라 재실행이 필요하다는 근거."""
    knobs = runner.TUNED_KNOBS["grasp-wp-alns"]
    assert knobs["rcl_size"] != DEFAULT_CONFIG.rcl_size
    assert knobs["angle_diversity_weight_m"] != DEFAULT_CONFIG.angle_diversity_weight_m
