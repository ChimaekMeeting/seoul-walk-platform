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
