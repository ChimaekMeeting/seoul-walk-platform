"""재생 화면이 읽는 payload를 순수 파이썬으로 검증한다.

화면 동작(JS)은 `test_player_selftest.py`가 실제 브라우저로 확인한다. 여기서는 그 화면이
읽을 데이터가 맞게 만들어지는지만 본다 — 지원 목록과 "새 실행 필요" 판정, 시나리오 요약,
랜드마크 좌표, 비교표 경고에 쓰는 실행 조건 차이.
"""

import json
import re

import pytest

from visualizations.route_view import (
    BASE_COMMAND,
    CONDITION_FIELDS,
    GRASP_COMMAND,
    LABELS,
    build_catalog,
    catalog_modes,
    condition_differences,
    condition_diff_map,
    describe_settings,
    landmark_points,
    render_player,
    scenario_summary,
)

SCENARIO = {
    "id": "sangmyung",
    "name": "상명대학교 서울캠퍼스 정문",
    "origin": {"name": "상명대학교 서울캠퍼스 정문", "lat": 37.601446, "lon": 126.955064},
    "destination": {"name": "경복궁역 3번 출입구", "lat": 37.5762348, "lon": 126.9726844},
}


def _result(mode, *, target_m=None, seed=42, num_waypoints=None, heuristic=None):
    config = {} if num_waypoints is None else {"num_waypoints": num_waypoints}
    return {"mode": mode,
            "conditions": {"target_m": target_m, "seed": seed, "config": config,
                           "heuristic": heuristic or {"name": "haversine"},
                           "service_use": "service"}}


def test_catalog_covers_every_refinement_from_the_real_registry():
    from src.route_engine.engines.waypoint_engine_assembly import REFINEMENT_REGISTRY

    modes = catalog_modes()
    assert modes[:4] == ["shortest", "shortest_alt", "detour", "circular"]
    assert [m for m in modes if m.startswith("grasp_")] == [f"grasp_{n}" for n in REFINEMENT_REGISTRY]
    assert set(modes) <= set(LABELS), "지원 목록의 모든 모드에 표시명이 있어야 합니다."


def test_catalog_marks_missing_results_as_needing_a_new_run():
    catalog = build_catalog([_result("shortest"), _result("circular")])
    available = {entry["mode"]: entry["available"] for entry in catalog}
    assert available["shortest"] and available["circular"]
    assert not available["shortest_alt"] and not available["grasp_vnd"]
    commands = {entry["mode"]: entry["command"] for entry in catalog}
    assert commands["circular"] == BASE_COMMAND
    assert commands["grasp_alns"] == GRASP_COMMAND
    assert all(entry["label"] == LABELS[entry["mode"]] for entry in catalog)


def test_catalog_is_all_available_when_every_mode_ran():
    catalog = build_catalog([_result(mode) for mode in catalog_modes()])
    assert all(entry["available"] for entry in catalog)


def test_scenario_summary_is_read_only_names():
    assert scenario_summary(SCENARIO) == {
        "id": "sangmyung", "name": "상명대학교 서울캠퍼스 정문",
        "origin": "상명대학교 서울캠퍼스 정문", "destination": "경복궁역 3번 출입구"}
    # 목적지가 없는 시나리오도 화면이 막히지 않아야 한다.
    assert scenario_summary({"id": "x"})["destination"] is None


@pytest.mark.parametrize("left,right,expected", [
    (_result("circular", target_m=3000), _result("grasp_vnd", target_m=3000), []),
    (_result("circular", target_m=3000), _result("circular", target_m=5000), ["target_m"]),
    (_result("circular", seed=42), _result("grasp_vnd", seed=7), ["seed"]),
    (_result("grasp_vnd", num_waypoints=2), _result("grasp_vns", num_waypoints=3), ["num_waypoints"]),
    (_result("circular", target_m=3000, seed=42),
     _result("grasp_vnd", target_m=5000, seed=7, num_waypoints=2),
     ["num_waypoints", "seed", "target_m"]),
    # 최단거리끼리는 목표 거리가 둘 다 없으므로 "다르다"고 보지 않는다.
    (_result("shortest"), _result("shortest_alt"), []),
])
def test_condition_differences_only_reports_real_gaps(left, right, expected):
    assert condition_differences(left, right) == expected
    assert set(expected) <= set(CONDITION_FIELDS)


def test_condition_diff_map_skips_results_that_match_everything():
    results = [_result("circular", target_m=3000), _result("grasp_vnd", target_m=3000),
               _result("grasp_vns", target_m=5000)]
    table = condition_diff_map(results)
    assert "circular" in table and table["circular"] == {"grasp_vns": ["target_m"]}
    assert table["grasp_vns"] == {"circular": ["target_m"], "grasp_vnd": ["target_m"]}
    assert set(table) == {"circular", "grasp_vnd", "grasp_vns"}


def test_landmark_points_are_empty_without_alt():
    assert landmark_points(_result("shortest")) == []
    alt = _result("shortest_alt", heuristic={"name": "alt_planar",
                                             "landmarks": [{"node": 1, "lat": 37.0, "lon": 127.0}]})
    assert landmark_points(alt) == [{"node": 1, "lat": 37.0, "lon": 127.0}]


def test_settings_line_ends_with_the_service_badge():
    assert describe_settings(_result("circular")).endswith("서비스 엔진")


def _minimal_payload():
    return {"nodes": {"1": [0, 0]}, "background": [], "radius": 300, "cases": [],
            "scenario": scenario_summary(SCENARIO), "catalog": build_catalog([_result("circular")]),
            "condition_diff": {}, "condition_labels": CONDITION_FIELDS, "results": []}


def test_render_player_inlines_style_script_and_data_without_external_requests():
    document = render_player(_minimal_payload())
    for placeholder in ("__ROUTE_STYLE__", "__ROUTE_SCRIPT__", "__ROUTE_DATA__"):
        assert placeholder not in document, f"{placeholder} 자리가 그대로 남았습니다."
    # 산출물은 인터넷·다른 로컬 파일을 더 읽지 않고 혼자 열려야 한다.
    assert not re.search(r"<script[^>]+src=", document)
    assert not re.search(r"<link[^>]+href=", document)
    assert "http://" not in document.replace("http://www.w3.org", "")
    assert "route_player.css" not in document and "route_player.js" not in document
    # 데이터는 <script type="application/json">에 그대로 실린다.
    embedded = re.search(r'<script id="route-data" type="application/json">(.*?)</script>',
                         document, re.S).group(1)
    assert json.loads(embedded)["scenario"]["id"] == "sangmyung"


def test_write_route_views_puts_the_picker_data_into_the_page(tmp_path):
    """생성된 routes.html의 payload에 선택 화면이 읽는 키가 실제로 들어가는지 본다.

    `build_catalog()` 같은 함수만 따로 검사하면 "만들어는 두고 payload에 안 넣는" 실수를
    잡지 못한다 — 실제로 한 번 놓쳤다. 그래서 생성물에서 직접 확인한다.
    """
    import networkx as nx

    from visualizations.route_experiment import execute
    from visualizations.route_story import prepare_story
    from visualizations.route_view import write_route_views
    from visualizations.tests.conftest import _grid_graph

    graph = _grid_graph()
    nx.set_edge_attributes(graph, 120.0, "length")
    start = {"node": 0, **graph.nodes[0]}
    recorded = execute(graph, "circular", start, start, 1500)
    recorded["route_valid"] = True
    prepare_story(graph, recorded)
    report = {"scenario": SCENARIO,
              "intent_cases": [{"request": "격자 1.5km 순환", "result": "circular"}],
              "results": [recorded]}
    write_route_views(graph, report, tmp_path)

    document = (tmp_path / "routes.html").read_text(encoding="utf-8")
    payload = json.loads(re.search(
        r'<script id="route-data" type="application/json">(.*?)</script>', document, re.S).group(1))
    assert payload["scenario"]["origin"] == "상명대학교 서울캠퍼스 정문"
    assert [entry["mode"] for entry in payload["catalog"]] == catalog_modes()
    assert [entry["mode"] for entry in payload["catalog"] if entry["available"]] == ["circular"]
    assert payload["condition_labels"] == CONDITION_FIELDS
    assert "condition_diff" in payload
    result = payload["results"][0]
    assert result["label"] == LABELS["circular"]
    assert result["settings"].endswith("서비스 엔진")
    assert result["conditions"]["service_use"] == "service"


def test_render_player_rejects_a_payload_that_would_break_out_of_the_script_tag():
    payload = _minimal_payload()
    payload["cases"] = [{"request": "</script><script>alert(1)</script>", "result": "circular"}]
    document = render_player(payload)
    # json.dumps 뒤 "<"를 <로 바꾸므로 태그가 닫히지 않는다.
    assert "</script><script>alert" not in document
    assert document.count("</script>") == 2
