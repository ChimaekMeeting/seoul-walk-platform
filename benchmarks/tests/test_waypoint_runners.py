"""경유지 실행기의 공통 입력과 측정 출력을 작은 그래프로 검증한다."""

import json
import sys

import networkx as nx
import pytest

from benchmarks.runner import _waypoint_common as common
from benchmarks.runner import waypoint_alns, waypoint_beam


@pytest.fixture
def graph(monkeypatch):
    graph = nx.path_graph(25)
    nx.set_node_attributes(graph, 37.5, "lat")
    nx.set_node_attributes(graph, 127.0, "lon")
    nx.set_edge_attributes(graph, 100.0, "length")
    monkeypatch.setattr(common.GraphArtifactRepository, "load", lambda *a, **kw: graph)
    return graph


def test_beam_repeats_reset_cache_and_preserve_result(graph, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["beam", "--repeats", "2"])
    waypoint_beam.main()
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 2
    assert rows[0]["best_ids"] == rows[1]["best_ids"]
    assert rows[0]["shortest_path_calls"] == rows[1]["shortest_path_calls"] > 0
    assert all(row["cost_calls"] > 0 for row in rows)


def test_alns_records_settings_and_uses_same_pool_as_beam(graph, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["beam", "--repeats", "1", "--target-m", "3100"])
    waypoint_beam.main()
    beam = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alns",
            "--target-m",
            "3100",
            "--seeds",
            "0",
            "1",
            "--iterations",
            "3",
            "--removal-fraction",
            "0.5",
            "--start-temperature-m",
            "0",
            "--segment-length",
            "1",
            "--reaction-factor",
            "0",
            "--candidate-limit",
            "4",
        ],
    )
    waypoint_alns.main()
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["seed"] for row in rows] == [0, 1]
    for row in rows:
        assert row["pool_ids"] == beam["pool_ids"]
        assert row["initial_ids"] == beam["best_ids"]
        assert row["best_error_m"] <= row["initial_error_m"]
        assert row["settings"]["removal_fraction"] == 0.5
        assert row["settings"]["start_temperature_m"] == 0


@pytest.mark.parametrize(
    "args",
    [
        ["--repeats", "0"],
        ["--start-id", "999"],
        ["--beam-width", "0"],
        ["--pool-size", "100"],
        ["--target-m", "nan"],
    ],
)
def test_bad_fixture_arguments_report_cli_error(graph, monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["beam", *args])
    with pytest.raises(SystemExit) as error:
        waypoint_beam.main()
    assert error.value.code == 2


def test_beam_compares_same_fixture_across_tolerances(graph, monkeypatch, capsys):
    """거리 전용과 두 허용 오차가 같은 후보를 사용하고 재통행을 보고한다."""
    monkeypatch.setattr(
        sys, "argv", ["beam", "--repeats", "1", "--tolerances", "0.025", "0.075"]
    )
    waypoint_beam.main()
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["tolerance_ratio"] for row in rows] == [None, 0.025, 0.075]
    assert all(row["pool_ids"] == rows[0]["pool_ids"] for row in rows)
    assert all(row["overlap_ratio"] == 0.5 for row in rows)
    assert rows[0]["route_evaluations"] == rows[0]["route_path_calls"] == 0
    assert rows[0]["validation_path_calls"] > 0
    assert all(row["route_evaluations"] > 0 for row in rows[1:])
    assert all(
        row["total_search_path_calls"]
        == row["shortest_path_calls"] + row["route_path_calls"]
        for row in rows
    )


def test_alns_comparison_preserves_initial_order_and_seed(graph, monkeypatch, capsys):
    """모든 모드의 초기 해와 seed가 같고 기존 거리 전용 조기 종료는 유지된다."""
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "alns",
            "--seeds",
            "2",
            "--iterations",
            "2",
            "--tolerances",
            "0.025",
            "0.05",
            "--start-temperature-score",
            "0",
        ],
    )
    waypoint_alns.main()
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 3
    assert all(
        row["initial_ids"] == rows[0]["initial_ids"] and row["seed"] == 2
        for row in rows
    )
    assert all(row["initial_overlap_ratio"] == 0.5 for row in rows)
    assert rows[0]["stop_reason"] == "exact_target"
    assert all(row["iterations"] == 2 for row in rows[1:])


def test_provided_initial_ids_do_not_invoke_beam(graph, monkeypatch, capsys):
    """동일 후보 풀의 외부 경유지 순서를 전달하면 Beam 생성 없이 개선한다."""
    parser = common.argument_parser("")
    args = parser.parse_args([])
    _, _, pool, _, _ = common.prepare_fixture(args, parser)
    ids = [str(c["node_id"]) for c in pool[:2]]

    def forbidden(**kwargs):
        """초기 해를 전달한 실행에서 Beam이 호출되면 실패한다."""
        pytest.fail("외부 초기 순서가 있는데 Beam을 호출했습니다.")

    monkeypatch.setattr(waypoint_alns, "beam_search", forbidden)
    monkeypatch.setattr(
        sys,
        "argv",
        ["alns", "--seeds", "0", "--iterations", "0", "--initial-ids", *ids],
    )
    waypoint_alns.main()
    row = json.loads(capsys.readouterr().out)
    assert row["initial_source"] == "provided"
    assert row["initial_ids"] == list(map(int, ids))


@pytest.mark.parametrize(
    "argv",
    [
        ["beam", "--tolerances", "nan"],
        ["beam", "--tolerances", "1"],
        ["beam", "--path-cache-size", "-1"],
        ["alns", "--tolerances", "0.05"],
        ["alns", "--start-temperature-score", "0.1"],
    ],
)
def test_invalid_comparison_arguments(graph, monkeypatch, argv):
    """불완전하거나 범위가 잘못된 비교 설정은 실행 전에 거부한다."""
    monkeypatch.setattr(sys, "argv", argv)
    runner = waypoint_beam if argv[0] == "beam" else waypoint_alns
    with pytest.raises(SystemExit) as error:
        runner.main()
    assert error.value.code == 2
