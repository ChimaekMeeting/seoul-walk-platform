"""
benchmarks/tests/test_algorithm_defaults.py

튜닝 확정값을 벤치마크 TUNED_KNOBS에서 엔진 알고리즘별 기본값으로 옮긴 뒤의 계약을 고정한다.

지키는 사고는 세 가지다.
  1. 벤치마크가 엔진 기본값을 우회하는 것 — 솔버가 설정을 DEFAULT_CONFIG로 채워 넘기면
     src/ 상수를 바꿔도 벤치마크는 옛 값으로 돈다. 그래서 솔버가 엔진에 실제로 넘기는 설정을
     가로채 확인한다(엔진 실행은 하지 않는다).
  2. 공용 기본값이 함께 바뀌는 것 — GraspConfig·_ALNS_ITERATIONS는 "기본값 유지"로 확정된
     조합(grasp-wp-local·vnd, beam-wp-alns 등)도 쓴다.
  3. 확정 한도가 ALNS 검증을 통과하지 못해 ALNS가 조용히 건너뛰어지는 것.
"""

import random
from dataclasses import replace

import networkx as nx
import pytest

from benchmarks import run_density_stratified_scenarios as runner
from benchmarks.benchmark import SOLVER_REGISTRY
from benchmarks.solvers import beam_waypoint_refinement_solver, grasp_waypoint_solver
from src.route_engine.engines import waypoint_refinement
from src.route_engine.engines.circular_beam_waypoint_vns import BEAM_VNS_CONFIG, CircularBeamWaypointVnsEngine
from src.route_engine.engines.circular_grasp_waypoint_alns import (
    GRASP_ALNS_CONFIG,
    GRASP_ALNS_OPTIONS,
    CircularGraspWaypointAlnsEngine,
)
from src.route_engine.engines.grasp_waypoint_common import DEFAULT_CONFIG
from src.route_engine.waypoint_alns import _validate
from src.schema.route_schema import CircularRouteInput


class _EngineCaptured(Exception):
    pass


@pytest.fixture
def solver_engine(monkeypatch):
    """solve(params)가 만든 엔진을 실행 직전에 돌려준다."""
    captured = {}

    def capture(engine, start_node, target_km):
        captured["engine"] = engine
        raise _EngineCaptured

    for module in (grasp_waypoint_solver, beam_waypoint_refinement_solver):
        monkeypatch.setattr(module, "run_circular_engine_distance_only", capture)

    def build(solver_key: str, params: dict):
        with pytest.raises(_EngineCaptured):
            SOLVER_REGISTRY[solver_key].solve(nx.Graph(), 1, 1, params)
        return captured["engine"]

    return build


# ── 1. 벤치마크가 엔진 기본값을 따르는가 ─────────────────────────────────────

def test_grasp_alns_solver_uses_engine_defaults_without_params(solver_engine):
    engine = solver_engine("grasp-wp-alns", {})

    assert engine.config == GRASP_ALNS_CONFIG
    assert engine.refinement_options == dict(GRASP_ALNS_OPTIONS)


def test_grasp_alns_sweep_overrides_one_knob_and_keeps_the_rest(solver_engine):
    """스윕은 노브 하나만 params로 바꾼다 — 나머지 확정값이 공용 기본값으로 떨어지면 안 된다."""
    engine = solver_engine("grasp-wp-alns", {"rcl_size": 8, "alns_iterations": 20})

    assert engine.config == replace(GRASP_ALNS_CONFIG, rcl_size=8)
    assert engine.config.angle_diversity_weight_m == GRASP_ALNS_CONFIG.angle_diversity_weight_m
    assert engine.refinement_options == {**GRASP_ALNS_OPTIONS, "iterations": 20}


def test_beam_vns_solver_uses_tuned_beam_width(solver_engine):
    assert solver_engine("beam-wp-vns", {}).config.rcl_size == BEAM_VNS_CONFIG.rcl_size
    assert solver_engine("beam-wp-vns", {"beam_width": 8}).config.rcl_size == 8


@pytest.mark.parametrize("solver_key", ["grasp-wp-local", "grasp-wp-vnd", "beam-wp-local", "beam-wp-alns"])
def test_solvers_without_their_own_defaults_stay_on_shared_defaults(solver_engine, solver_key):
    """grasp-wp-local·vnd의 rcl_size=8, beam-wp-alns의 beam_width=8은 "기본값 유지"로 확정됐다."""
    engine = solver_engine(solver_key, {})

    assert engine.config == DEFAULT_CONFIG
    assert not engine.refinement_options


def test_engine_wrappers_default_to_algorithm_configs():
    """src/를 직접 쓰는 호출자(서비스 연결 등)도 옵션 없이 확정값을 받아야 한다."""
    inp = CircularRouteInput(start_lat=0.0, start_lon=0.0, target_km=3.0)

    grasp_alns = CircularGraspWaypointAlnsEngine(inp=inp, G=nx.Graph())
    assert grasp_alns.config == GRASP_ALNS_CONFIG
    assert grasp_alns.refinement_options == dict(GRASP_ALNS_OPTIONS)

    beam_vns = CircularBeamWaypointVnsEngine(inp=inp, G=nx.Graph(), vns_options={"max_shake_level": 2})
    assert beam_vns.config == BEAM_VNS_CONFIG
    assert (beam_vns.construction, beam_vns.refinement) == ("beam", "vns")
    assert beam_vns.refinement_options == {"max_shake_level": 2}


@pytest.mark.parametrize("solver_key", ["grasp-wp-alns", "beam-wp-vns"])
def test_runner_metadata_matches_what_the_solver_actually_sends(solver_engine, solver_key):
    """러너가 메타데이터에 남기는 설정과 솔버가 엔진에 넘기는 설정이 갈라지면 기록이 거짓이 된다."""
    engine = solver_engine(solver_key, {})
    recorded = runner.algorithm_defaults([solver_key])[solver_key]

    assert recorded["config"]["rcl_size"] == engine.config.rcl_size
    assert recorded["config"]["angle_diversity_weight_m"] == engine.config.angle_diversity_weight_m
    assert recorded.get("alns_options", {}) == (engine.refinement_options or {})


# ── 2. 공용 기본값은 그대로인가 ─────────────────────────────────────────────

def test_algorithm_configs_differ_from_shared_defaults_only_in_tuned_fields():
    assert replace(
        GRASP_ALNS_CONFIG,
        rcl_size=DEFAULT_CONFIG.rcl_size,
        angle_diversity_weight_m=DEFAULT_CONFIG.angle_diversity_weight_m,
    ) == DEFAULT_CONFIG
    assert replace(BEAM_VNS_CONFIG, rcl_size=DEFAULT_CONFIG.rcl_size) == DEFAULT_CONFIG


def test_shared_defaults_are_untouched():
    """확정값을 공용 기본값에 직접 넣으면 이 테스트가 먼저 깨진다 — 알고리즘별 상수에 넣을 것."""
    assert DEFAULT_CONFIG.rcl_size == 8
    assert DEFAULT_CONFIG.angle_diversity_weight_m == 1500.0
    assert waypoint_refinement._ALNS_ITERATIONS == 30


# ── 3. 확정 한도가 실제 ALNS 설정까지 닿고 검증을 통과하는가 ─────────────────

def _grasp_alns_config(engine):
    """엔진이 find_path() 안에서 만드는 것과 같은 경로로 ALNSConfig를 만든다."""
    return waypoint_refinement._alns_config(7000.0, engine.config, random.Random(0), engine.refinement_options)


def test_grasp_alns_candidate_limit_is_decoupled_from_rcl_size(solver_engine):
    """#434 — 한도를 따로 주지 않으면 cfg.rcl_size(=16)를 따라간다. 한도 2가 ALNSConfig까지
    닿는지와, rcl_size는 구축 RCL 값으로 그대로 남는지를 함께 고정한다."""
    config = _grasp_alns_config(solver_engine("grasp-wp-alns", {}))

    assert config.candidate_limit == GRASP_ALNS_OPTIONS["candidate_limit"]
    assert config.iterations == GRASP_ALNS_OPTIONS["iterations"]
    assert config.candidate_limit != GRASP_ALNS_CONFIG.rcl_size


@pytest.mark.parametrize("num_waypoints", runner._load_dataset()["num_waypoints"])
def test_grasp_alns_candidate_limit_is_valid_for_every_grid_n(solver_engine, num_waypoints):
    """candidate_limit < remove_count면 alns_search가 ValueError를 내고, 엔진은 경고만 남긴 채
    ALNS를 건너뛴다(waypoint_refinement.py) — 행은 ok로 쌓이지만 사실상 정제 없는 결과다.
    격자의 모든 N에서 검증을 통과해야 한다."""
    config = _grasp_alns_config(solver_engine("grasp-wp-alns", {"num_waypoints": num_waypoints}))
    initial_ids = tuple(range(1, num_waypoints + 1))
    candidates = [{"node_id": node, "lat": 0.0, "lon": 0.0} for node in range(1, num_waypoints + 4)]

    _, remove_count = _validate(candidates, initial_ids, 0, 0, 7000.0, config)

    assert remove_count <= config.candidate_limit
