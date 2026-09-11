"""
benchmarks/tests/test_run_metadata_and_checks.py

J(재현 메타데이터)·K(결과 CSV 완전성 검사) 검증.

K의 테스트는 특히 "실제로 났던 버그를 다시 잡는가"에 초점을 둔다 — 컬럼이 추가됐는데
러너가 안 채워 전 행 NaN이 되는 상황이 이 저장소에서 반복됐다.
"""

import json

import pandas as pd

from benchmarks import check_results, run_metadata
from benchmarks.results import RESULT_COLUMNS


def _result_frame(algorithm="GRASP-Waypoint+Local", n=3, **overrides):
    base = {column: None for column in RESULT_COLUMNS}
    base.update({
        "algorithm": algorithm, "status": "ok", "elapsed_sec": 1.0, "cost": 3000.0,
        "target_km": 3.0, "distance_km": 3.0, "distance_deviation_km": 0.0,
        "is_closed_loop": True, "spike_count": 0, "repeated_edge_ratio": 0.0,
        "circularity_q": 0.4, "passed": True,
        "num_waypoints_used": 2, "effective_waypoints_used": 2,
        "selection_status": "feasible", "feasible": True,
        "pool_cache_hits": 100, "pool_cache_misses": 5,
        "error": "",
    })
    base.update(overrides)
    return pd.DataFrame([base] * n)


# ── J ────────────────────────────────────────────────────────────────────

def test_j1_metadata_records_code_and_environment_identity():
    payload = run_metadata.collect_metadata("test_runner", seeds=[1, 2], workers=6)

    assert payload["runner"] == "test_runner"
    assert payload["run"] == {"seeds": [1, 2], "workers": 6}
    assert payload["environment"]["python"]
    assert "pandas" in payload["environment"]
    # 결과를 좌우하는 소스가 해시로 고정돼야 "같은 코드였는가"를 나중에 확인할 수 있다.
    assert payload["code_sha256"]["benchmarks/results.py"]
    assert payload["code_sha256"]["src/route_engine/waypoint_route_builder.py"]


def test_j2_metadata_path_sits_next_to_the_csv():
    assert run_metadata.metadata_path_for("a/b/results.csv").name == "results.metadata.json"


def test_j3_metadata_is_written_as_readable_json(tmp_path):
    csv_path = tmp_path / "results.csv"
    csv_path.write_text("x\n", encoding="utf-8")

    saved = run_metadata.save_run_metadata(
        csv_path, runner="run_geometry_validation", seeds=[42], algos=["grasp-wp-local"],
    )
    payload = json.loads(saved.read_text(encoding="utf-8"))

    assert saved.exists()
    assert payload["run"]["algos"] == ["grasp-wp-local"]
    assert payload["git"]["commit"] is None or len(payload["git"]["commit"]) == 40


def test_j4_metadata_overwrites_on_rerun(tmp_path):
    """격자 러너는 같은 CSV를 반복 실행하는 것이 정상이므로 덮어써야 한다
    (waypoint_overlap_audit.save_json의 'x' 모드와 다른 점)."""
    csv_path = tmp_path / "results.csv"
    csv_path.write_text("x\n", encoding="utf-8")

    run_metadata.save_run_metadata(csv_path, runner="first", seeds=[1])
    saved = run_metadata.save_run_metadata(csv_path, runner="second", seeds=[2])

    assert json.loads(saved.read_text(encoding="utf-8"))["runner"] == "second"


# ── K ────────────────────────────────────────────────────────────────────

def test_k1_complete_result_frame_passes():
    violations, _ = check_results.check(_result_frame())

    assert violations == []


def test_k2_missing_schema_column_is_a_violation():
    frame = _result_frame().drop(columns=["circularity_q"])

    violations, _ = check_results.check(frame)

    assert any("스키마 누락" in v and "circularity_q" in v for v in violations)


def test_k3_the_actual_historical_bug_is_caught():
    """러너가 경유지 컬럼을 안 채워 전 행 NaN이던 실제 버그를 잡는지 확인.

    num_waypoints_used / effective_waypoints_used / pool_cache_* 네 컬럼이 러너 4종
    전부에서 비어 있었다(2026-09-10 이전).
    """
    frame = _result_frame(
        num_waypoints_used=None, effective_waypoints_used=None,
        pool_cache_hits=None, pool_cache_misses=None,
    )

    violations, _ = check_results.check(frame)

    assert any("num_waypoints_used" in v for v in violations)
    assert any("effective_waypoints_used" in v for v in violations)
    assert any("pool_cache_hits" in v for v in violations)


def test_k4_legacy_solver_is_not_required_to_fill_waypoint_columns():
    """레거시 solver(GRASP+VNS 등)는 경유지 개념이 없다 — 비어 있어도 위반이 아니다."""
    frame = _result_frame(
        algorithm="GRASP+VNS",
        num_waypoints_used=None, effective_waypoints_used=None,
        selection_status=None, feasible=None,
        pool_cache_hits=None, pool_cache_misses=None,
    )

    violations, _ = check_results.check(frame)

    assert violations == []


def test_k5_beam_waypoint_is_not_required_to_fill_grasp_pool_columns():
    """Beam-Waypoint는 자체 풀을 만들어 GRASP 풀 캐시 지표를 보고하지 않는다."""
    frame = _result_frame(
        algorithm="Beam-Waypoint", pool_cache_hits=None, pool_cache_misses=None,
    )

    violations, _ = check_results.check(frame)

    assert violations == []


def test_k6_all_empty_column_is_reported_with_its_owner():
    """전 행이 빈 컬럼은 실패가 아니라 '누가 채웠어야 하는지'와 함께 보고된다."""
    _, notes = check_results.check(_result_frame())

    assert any("overlap_ratio" in note and "편도" in note for note in notes)


def test_k7_failed_rows_do_not_trigger_value_violations():
    """실패 행은 원래 지표가 비어 있다 — 검사 대상이 아니다."""
    frame = _result_frame(
        status="failed", passed=False, num_waypoints_used=None,
        effective_waypoints_used=None, selection_status=None, feasible=None,
        repeated_edge_ratio=None, pool_cache_hits=None, pool_cache_misses=None,
    )

    violations, notes = check_results.check(frame)

    assert violations == []
    assert any("성공(status == 'ok') 행이 없어" in note for note in notes)


def test_k8_cli_exit_code_signals_failure(tmp_path, capsys):
    """CI에 그대로 걸 수 있도록 위반 시 1을 반환해야 한다."""
    good = tmp_path / "good.csv"
    bad = tmp_path / "bad.csv"
    _result_frame().to_csv(good, index=False)
    _result_frame(num_waypoints_used=None).to_csv(bad, index=False)

    assert check_results.main([str(good)]) == 0
    assert check_results.main([str(bad)]) == 1
    assert "num_waypoints_used" in capsys.readouterr().out


def test_k9_coverage_table_shows_per_algorithm_fill_rates():
    frame = pd.concat([
        _result_frame("GRASP-Waypoint+Local"),
        _result_frame("GRASP+VNS", num_waypoints_used=None, effective_waypoints_used=None),
    ], ignore_index=True)

    coverage = check_results.coverage_by_algorithm(frame).set_index("algorithm")

    assert coverage.loc["GRASP-Waypoint+Local", "num_waypoints_used"] == 1.0
    assert coverage.loc["GRASP+VNS", "num_waypoints_used"] == 0.0
