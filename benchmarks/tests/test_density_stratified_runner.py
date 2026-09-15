"""
benchmarks/tests/test_density_stratified_runner.py

밀도 층화 러너의 실행 전 안전장치 검증(2026-09-14, 이슈 #427 튜닝값 반영 후 부분 재실행).

이 러너의 산출물은 한 번 돌리는 데 수십 분이 들고, 과거 실행분이 "GRASP-Waypoint+VNS
제외" 같은 판단의 유일한 근거로 남는다. 그래서 여기서 지키는 것은 수치가 아니라 두 가지
사고다 — 오타 난 --algos로 빈 격자를 돌려놓고 결과를 기다리는 것, 그리고 기존 CSV를
말없이 덮어써 근거를 잃는 것.
"""

import random

import pytest

from benchmarks import run_density_stratified_scenarios as runner
from benchmarks.benchmark import SEED_SENSITIVE_SOLVERS
from benchmarks.config import BENCHMARK_SEEDS
from benchmarks.solvers.beam_waypoint_refinement_solver import _DEFAULT_BEAM_WIDTH
from benchmarks.solvers.grasp_waypoint_solver import (
    _grasp_config_from_params, _refinement_options_from_params,
)
from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG
from src.route_engine.engines.waypoint_refinement import _alns_config
from src.route_engine.waypoint_alns import _validate


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


def _grasp_alns_config():
    """솔버와 같은 경로(params → 정제 options → ALNSConfig)로 grasp-wp-alns의 실제 ALNS 설정을 만든다."""
    knobs = runner.TUNED_KNOBS["grasp-wp-alns"]
    return _alns_config(
        target_m=7000.0, cfg=_grasp_config_from_params(knobs), rng=random.Random(0),
        options=_refinement_options_from_params("alns", knobs),
    )


def test_grasp_alns_candidate_limit_is_decoupled_from_rcl_size():
    """#434 — 한도를 따로 주지 않으면 엔진은 cfg.rcl_size(=16)를 쓴다. 한도 2가 ALNSConfig까지
    실제로 닿는지와, rcl_size는 구축 RCL 값으로 그대로 남는지를 함께 고정한다.
    이 값이 바뀌면 density_stratified_stage1_retuned.csv의 grasp-wp-alns 행 재사용 판단도 바뀐다."""
    config = _grasp_alns_config()

    assert config.candidate_limit == 2
    assert config.iterations == runner.TUNED_KNOBS["grasp-wp-alns"]["alns_iterations"]
    assert config.candidate_limit != runner.TUNED_KNOBS["grasp-wp-alns"]["rcl_size"]


@pytest.mark.parametrize("num_waypoints", runner._load_dataset()["num_waypoints"])
def test_grasp_alns_candidate_limit_is_valid_for_every_grid_n(num_waypoints):
    """candidate_limit < remove_count면 alns_search가 ValueError를 내고, 엔진은 경고만 남긴 채
    ALNS를 건너뛴다(waypoint_refinement.py) — 행은 ok로 쌓이지만 사실상 정제 없는 결과다.
    격자의 모든 N에서 검증을 통과해야 한다."""
    initial_ids = tuple(range(1, num_waypoints + 1))
    candidates = [{"node_id": node, "lat": 0.0, "lon": 0.0} for node in range(1, num_waypoints + 4)]

    _, remove_count = _validate(candidates, initial_ids, 0, 0, 7000.0, _grasp_alns_config())

    assert remove_count <= runner.TUNED_KNOBS["grasp-wp-alns"]["alns_candidate_limit"]
