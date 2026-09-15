"""
benchmarks/tests/test_density_stratified_runner.py

밀도 층화 러너의 실행 전 안전장치 검증(2026-09-14, 이슈 #427 튜닝값 반영 후 부분 재실행).

이 러너의 산출물은 한 번 돌리는 데 수십 분이 들고, 과거 실행분이 "GRASP-Waypoint+VNS
제외" 같은 판단의 유일한 근거로 남는다. 그래서 여기서 지키는 것은 수치가 아니라 두 가지
사고다 — 오타 난 --algos로 빈 격자를 돌려놓고 결과를 기다리는 것, 그리고 기존 CSV를
말없이 덮어써 근거를 잃는 것.
"""

import json

import pytest

from benchmarks import run_density_stratified_scenarios as runner
from benchmarks.benchmark import SEED_SENSITIVE_SOLVERS
from benchmarks.config import BENCHMARK_SEEDS
from src.route_engine.engines.circular_beam_waypoint_vns import BEAM_VNS_CONFIG
from src.route_engine.engines.circular_grasp_waypoint_alns import GRASP_ALNS_CONFIG, GRASP_ALNS_OPTIONS


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


def test_metadata_records_only_algorithms_with_their_own_defaults():
    """어떤 설정으로 돈 실행인지는 행만 보고 알 수 없어 메타데이터에 남긴다. 공용 기본값을 쓰는
    알고리즘까지 적으면 "튜닝값이 들어간 알고리즘"을 가려내기 어려워지므로 둘만 남긴다."""
    recorded = runner.algorithm_defaults(runner.ALGOS)

    assert set(recorded) == {"grasp-wp-alns", "beam-wp-vns"}
    assert recorded["grasp-wp-alns"]["config"]["rcl_size"] == GRASP_ALNS_CONFIG.rcl_size
    assert recorded["grasp-wp-alns"]["alns_options"] == dict(GRASP_ALNS_OPTIONS)
    assert recorded["beam-wp-vns"]["config"]["rcl_size"] == BEAM_VNS_CONFIG.rcl_size
    json.dumps(recorded)  # save_run_metadata가 그대로 직렬화할 수 있어야 한다


def test_metadata_honours_the_algo_subset():
    assert runner.algorithm_defaults(["grasp-wp-local", "beam-wp"]) == {}
    assert set(runner.algorithm_defaults(["beam-wp-vns"])) == {"beam-wp-vns"}
