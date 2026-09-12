"""기록 불변식 점검기가 실제로 어긋난 기록을 잡는지 확인한다.

정상 결과 폴더에서 전부 통과하는 것만 보면 "아무것도 검사하지 않는 점검기"와 구분되지
않는다. 그래서 기록을 한 군데씩 일부러 깨뜨려, 그때마다 **의도한 항목이 실패하는지**와
**관계없는 항목은 그대로 통과하는지**를 함께 본다.
"""

import copy
import json
import re
import shutil

import networkx as nx
import pytest

from visualizations.checks import PAYLOAD_PATTERN, run_checks
from visualizations.route_experiment import compare_recording, execute
from visualizations.route_story import prepare_story
from visualizations.route_view import write_route_views
from visualizations.tests.conftest import _grid_graph

SCENARIO = {
    "id": "grid", "name": "테스트 격자",
    "origin": {"name": "격자 좌하단"}, "destination": {"name": "격자 우상단"},
}
# (모드, 도착점이 출발점과 같은가, 목표 거리)
CASES = (("shortest", False, None), ("circular", True, 1500), ("grasp_alns", True, 1500))


def _build_run(folder):
    """toy 격자로 run_suite와 같은 모양의 결과 폴더를 만든다(엔진은 실제로 돈다)."""
    graph = _grid_graph()
    nx.set_edge_attributes(graph, 120.0, "length")
    start = {"node": 0, **graph.nodes[0]}
    end = {"node": 24, **graph.nodes[24]}
    SCENARIO["origin"].update(lat=graph.nodes[0]["lat"], lon=graph.nodes[0]["lon"])
    shortest_m = nx.dijkstra_path_length(graph, 0, 24, weight="length")
    results = []
    for mode, circular, target in CASES:
        finish = start if circular else end
        options = {"grasp_iterations": 2, "seed": 42}
        recorded = execute(graph, mode, start, finish, target, **options)
        plain = execute(graph, mode, start, finish, target, record=False, **options)
        recorded["recording_preserves_result"] = compare_recording(recorded, plain)
        recorded["run_seconds"] = plain["run_seconds"]
        recorded["route_valid"] = bool(recorded["metrics"]) and all(
            m["connected"] and m["endpoints_match"] for m in recorded["metrics"])
        if mode.startswith("shortest"):
            recorded["dijkstra_distance_m"] = shortest_m
            recorded["matches_dijkstra"] = True
        prepare_story(graph, recorded)
        results.append(recorded)
    report = {
        "code_commit": "0000000", "scenario": SCENARIO,
        "graph_unchanged": True, "input_files_unchanged": True,
        "intent_cases": [{"request": mode, "result": mode} for mode, _, _ in CASES],
        "results": results,
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "trace.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    write_route_views(graph, report, folder)
    summary = {**report, "results": [{k: v for k, v in r.items() if k not in ("trace", "responses")}
                                     for r in results]}
    (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                         encoding="utf-8")
    return graph


@pytest.fixture(scope="module")
def run_folder(tmp_path_factory):
    folder = tmp_path_factory.mktemp("run")
    _build_run(folder)
    return folder


@pytest.fixture(scope="module")
def grid_graph():
    graph = _grid_graph()
    nx.set_edge_attributes(graph, 120.0, "length")
    return graph


def _failed(payload):
    return {check["name"] for check in payload["checks"] if not check["passed"]}


def _broken(run_folder, tmp_path, mutate):
    """결과 폴더를 복사해 한 군데만 깨뜨린 뒤 점검한다(원본은 건드리지 않는다)."""
    copy_folder = tmp_path / "broken"
    shutil.copytree(run_folder, copy_folder)
    mutate(copy_folder)
    return run_checks(copy_folder, write=False)


def _edit_trace(folder, change):
    report = json.loads((folder / "trace.json").read_text(encoding="utf-8"))
    change(report)
    (folder / "trace.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")


def _first(report, mode):
    return next(r for r in report["results"] if r["mode"] == mode)


# ── 정상 폴더 ────────────────────────────────────────────────
def test_healthy_run_passes_every_check(run_folder):
    payload = run_checks(run_folder, write=False)
    assert payload["passed"], [c for c in payload["checks"] if not c["passed"]]
    assert {check["name"] for check in payload["checks"]} == set("ABCDEFGHIJ")
    # 그래프를 주지 않으면 거리 재측정만 건너뛴다.
    skipped = [check["name"] for check in payload["checks"] if check["skipped"]]
    assert skipped == ["E"]


def test_distance_recheck_runs_with_a_graph(run_folder, grid_graph):
    payload = run_checks(run_folder, graph=grid_graph, write=False)
    assert payload["passed"], [c for c in payload["checks"] if not c["passed"]]
    assert payload["distance_recheck"] is True
    assert all(not check["skipped"] for check in payload["checks"])


def test_checks_json_is_written_next_to_the_results(run_folder, tmp_path):
    copy_folder = tmp_path / "written"
    shutil.copytree(run_folder, copy_folder)
    run_checks(copy_folder)
    saved = json.loads((copy_folder / "checks.json").read_text(encoding="utf-8"))
    assert saved["passed"] and saved["results"] == len(CASES)


# ── 일부러 깨뜨린 기록 ───────────────────────────────────────
def test_skipped_seq_is_caught(run_folder, tmp_path):
    def mutate(folder):
        _edit_trace(folder, lambda report: _first(report, "circular")["trace"][3].update(seq=99))
    failed = _failed(_broken(run_folder, tmp_path, mutate))
    assert failed == {"A", "B"}, failed


def test_missing_final_event_is_caught(run_folder, tmp_path):
    def mutate(folder):
        _edit_trace(folder, lambda report: _first(report, "circular")["trace"].pop())
    failed = _failed(_broken(run_folder, tmp_path, mutate))
    assert failed == {"A", "B"}, failed


def test_kept_candidate_also_marked_rejected_is_caught(run_folder, tmp_path):
    def mutate(folder):
        def change(report):
            events = _first(report, "circular")["trace"]
            # 탈락 장면이 있는 반복을 먼저 찾고, 같은 반복의 유지 후보 하나를 거기에 끼워 넣는다.
            drop = next(e for e in events if e["kind"] == "reject"
                        and (e.get("values") or {}).get("iteration") is not None)
            iteration = drop["values"]["iteration"]
            keep = next(e for e in events if e["kind"] == "select"
                        and (e.get("values") or {}).get("iteration") == iteration)
            drop["paths"].append(copy.deepcopy(keep["paths"][0]))
        _edit_trace(folder, change)
    failed = _failed(_broken(run_folder, tmp_path, mutate))
    assert failed == {"D"}, failed


def test_internal_alns_acceptance_promoted_to_select_is_caught(run_folder, tmp_path):
    def mutate(folder):
        def change(report):
            events = _first(report, "grasp_alns")["trace"]
            internal = next(e for e in events if e.get("source_phase") == "alns_accept")
            internal["kind"] = "select"
            internal["decision"] = {"accepted": True, "reason": "내부 수락을 최종 채택처럼 올린 경우"}
        _edit_trace(folder, change)
    failed = _failed(_broken(run_folder, tmp_path, mutate))
    assert failed == {"D"}, failed


def test_candidate_node_mixed_into_the_final_route_is_caught(run_folder, tmp_path):
    def mutate(folder):
        def change(report):
            result = _first(report, "circular")
            chosen = set()
            for event in result["trace"]:
                if event["kind"] in ("select", "route_changed", "cleanup", "final"):
                    for path in event["paths"]:
                        chosen.update(path)
            explored = set()
            for event in result["trace"]:
                if event["kind"] in ("candidates", "reject"):
                    for path in event["paths"]:
                        explored.update(path)
            stray = sorted(explored - chosen - {result["start"]["node"], result["end"]["node"]})
            assert stray, "격자에서 탐색만 하고 고르지 않은 노드가 있어야 이 검사가 의미 있다."
            result["trace"][-1]["paths"][0].append(stray[0])
        _edit_trace(folder, change)
    failed = _failed(_broken(run_folder, tmp_path, mutate))
    assert failed == {"F"}, failed


def test_comparison_table_out_of_sync_with_summary_is_caught(run_folder, tmp_path):
    def mutate(folder):
        document = (folder / "routes.html").read_text(encoding="utf-8")
        payload = json.loads(PAYLOAD_PATTERN.search(document).group(1))
        payload["results"][0]["metrics"][0]["distance_m"] += 1.0
        serialized = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
        (folder / "routes.html").write_text(
            PAYLOAD_PATTERN.sub(
                lambda _: '<script id="route-data" type="application/json">'
                          + serialized.replace("\\", "\\\\") + "</script>",
                document, count=1),
            encoding="utf-8")
    failed = _failed(_broken(run_folder, tmp_path, mutate))
    assert failed == {"G"}, failed


def test_tampered_stage_distance_is_caught_only_with_a_graph(run_folder, tmp_path, grid_graph):
    """E는 그래프가 있어야 돈다. 없으면 잡지 못하고 '건너뜀'으로 남는다."""
    def mutate(folder):
        def change(report):
            event = next(e for e in _first(report, "circular")["trace"] if e.get("stage_metrics"))
            event["stage_metrics"]["distance_m"] += 5.0
        _edit_trace(folder, change)
    copy_folder = tmp_path / "tampered"
    shutil.copytree(run_folder, copy_folder)
    mutate(copy_folder)
    assert _failed(run_checks(copy_folder, write=False)) == set()
    assert _failed(run_checks(copy_folder, graph=grid_graph, write=False)) == {"E"}


def test_recording_flags_must_be_true(run_folder, tmp_path):
    def mutate(folder):
        summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
        summary["results"][0]["recording_preserves_result"] = False
        summary["graph_unchanged"] = False
        (folder / "summary.json").write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
    payload = _broken(run_folder, tmp_path, mutate)
    assert _failed(payload) == {"H"}
    violations = next(c for c in payload["checks"] if c["name"] == "H")["violations"]
    assert len(violations) == 2


def test_missing_timing_phrase_in_the_page_is_caught(run_folder, tmp_path):
    def mutate(folder):
        document = (folder / "routes.html").read_text(encoding="utf-8")
        (folder / "routes.html").write_text(document.replace("계산 시간이 아닙니다", "계산 시간입니다"),
                                            encoding="utf-8")
    failed = _failed(_broken(run_folder, tmp_path, mutate))
    assert failed == {"I"}, failed


def test_payload_missing_from_the_page_stops_the_check(run_folder, tmp_path):
    copy_folder = tmp_path / "nopayload"
    shutil.copytree(run_folder, copy_folder)
    document = (copy_folder / "routes.html").read_text(encoding="utf-8")
    (copy_folder / "routes.html").write_text(
        re.sub(r'<script id="route-data".*?</script>', "", document, flags=re.S), encoding="utf-8")
    with pytest.raises(ValueError, match="payload"):
        run_checks(copy_folder, write=False)
