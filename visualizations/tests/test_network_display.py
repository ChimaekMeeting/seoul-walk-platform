"""표시 범위 집계와 결과 경로 경계의 회귀 검증."""

import json
import math

import networkx as nx
import pytest

from visualizations.network_view import EARTH_RADIUS_M, _segments_in_square
from visualizations.run import _load_scenario, _new_run_directory


@pytest.mark.parametrize("scenario_id", [
    "../escape", r"..\escape", "/absolute", r"C:\absolute", "C:relative",
    "", ".", "..", "CON", "nul", "LPT1", "name.", None, 123,
])
def test_invalid_id_does_not_create_output(tmp_path, scenario_id):
    output = tmp_path / "outputs"
    with pytest.raises(ValueError, match="시나리오 id"):
        _new_run_directory(output, scenario_id)
    assert not output.exists()


def test_existing_output_is_preserved_and_new_run_stays_inside(tmp_path):
    first = _new_run_directory(tmp_path, "sangmyung")
    marker = first / "keep.txt"
    marker.write_text("existing result", encoding="utf-8")
    second = _new_run_directory(tmp_path, "sangmyung")
    assert first != second
    assert second.is_relative_to(tmp_path.resolve())
    assert marker.read_text(encoding="utf-8") == "existing result"


def test_existing_external_symlink_is_rejected(tmp_path):
    output = tmp_path / "outputs"
    outside = tmp_path / "outside"
    output.mkdir()
    outside.mkdir()
    try:
        (output / "sangmyung").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("이 환경에서는 디렉터리 심볼릭 링크 생성 권한이 없습니다.")
    with pytest.raises(ValueError, match="출력 폴더"):
        _new_run_directory(output, "sangmyung")
    assert list(outside.iterdir()) == []


def test_view_counts_inside_nodes_and_clips_crossing_edges():
    graph = nx.Graph()
    # 표시 반폭은 10m. 3-4는 경계 상자만 겹치고 실제 선은 영역 밖이다.
    positions = {0: (0, 0), 1: (5, 0), 2: (20, 0), 3: (8, 20),
                 4: (20, 8), 5: (-20, -5), 6: (20, -5)}
    for node, (x, y) in positions.items():
        graph.add_node(node, lat=math.degrees(y / EARTH_RADIUS_M),
                       lon=math.degrees(x / EARTH_RADIUS_M))
    graph.add_edges_from([(0, 1), (1, 2), (3, 4), (5, 6)])
    before = nx.node_link_data(graph)
    segments, nodes = _segments_in_square(graph, 0, 0, 10)
    assert nodes == {0, 1}
    assert len(segments) == 3
    assert all(-10 <= x <= 10 and -10 <= y <= 10
               for segment in segments for x, y in segment)
    assert any(start[0] == -10 and end[0] == 10 for start, end in segments)
    assert nx.node_link_data(graph) == before


@pytest.mark.parametrize("changes", [
    {"coordinate_source_url": ""}, {"coordinate_source_url": "   "},
    {"coordinate_source_url": "file:///local"}, {"coordinate_source_url": "https://"},
    {"verified_date": ""}, {"verified_date": "2026-02-30"},
    {"verified_date": "20260910"}, {"verified_date": None},
])
def test_missing_or_malformed_provenance_is_rejected(tmp_path, changes):
    origin = {"lat": 37.601446, "lon": 126.955064,
              "coordinate_source_url": "https://example.com/map", "verified_date": "2026-09-10"}
    origin.update(changes)
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps({"id": "sangmyung", "origin": origin}), encoding="utf-8")
    with pytest.raises(ValueError):
        _load_scenario(str(path))
