"""재생 화면(JS)을 실제 브라우저에서 돌려 자가 점검 결과를 확인한다.

`route_player.js`는 `?selftest=1`이면 모든 결과 × 모든 장면을 실제로 그려 보고 결과를
`<pre id="selftest-result">`에 JSON으로 남긴다. 이 테스트는 그 JSON을 읽어 실패가 0인지
보고, 콘솔에 `Uncaught`가 없는지도 확인한다. 데스크톱과 모바일 두 화면 크기로 돌린다.

Chrome 실행 파일이 없으면 건너뛴다 — CI·다른 개발 환경에서 이 파일 때문에 전체 테스트가
실패하지 않게 하기 위해서다. 순수 파이썬 쪽 검증은 `test_route_view_payload.py`가 한다.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from visualizations.route_experiment import execute
from visualizations.route_story import prepare_story
from visualizations.route_view import write_route_views

CHROME_CANDIDATES = (
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
)
# (이름, 폭, 높이). 모바일은 화면이 좁아 미니맵·선택 화면 배치가 달라진다.
VIEWPORTS = (("desktop", 1280, 800), ("mobile", 390, 844))
SELFTEST_RESULT = re.compile(r'<pre id="selftest-result">(.*?)</pre>', re.S)


def _chrome():
    for candidate in CHROME_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return shutil.which("chrome") or shutil.which("google-chrome")


@pytest.fixture(scope="module")
def player(tmp_path_factory):
    """toy 격자로 실제 실행 기록을 만들고 routes.html을 생성한다."""
    from visualizations.tests.conftest import _grid_graph
    import networkx as nx

    graph = _grid_graph()
    nx.set_edge_attributes(graph, 120.0, "length")
    start = {"node": 0, **graph.nodes[0]}
    end = {"node": 24, **graph.nodes[24]}
    results = []
    for mode, finish, target in (("shortest", end, None), ("circular", start, 1500)):
        recorded = execute(graph, mode, start, finish, target)
        recorded["route_valid"] = bool(recorded["metrics"]) and all(
            m["connected"] and m["endpoints_match"] for m in recorded["metrics"])
        prepare_story(graph, recorded)
        results.append(recorded)
    report = {
        "scenario": {"id": "grid", "name": "테스트 격자",
                     "origin": {"name": "격자 좌하단", "lat": graph.nodes[0]["lat"],
                                "lon": graph.nodes[0]["lon"]},
                     "destination": {"name": "격자 우상단"}},
        "intent_cases": [{"request": "격자 최단거리", "result": "shortest"},
                         {"request": "격자 1.5km 순환", "result": "circular"}],
        "results": results,
    }
    output = tmp_path_factory.mktemp("player")
    write_route_views(graph, report, output)
    return output / "routes.html"


def _run(chrome, page, profile, width, height):
    process = subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
         f"--user-data-dir={profile}", f"--window-size={width},{height}",
         "--enable-logging=stderr", "--v=1", "--virtual-time-budget=30000",
         "--dump-dom", page.as_uri() + "?selftest=1"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    return process.stdout, process.stderr


def test_generated_page_has_no_external_requests(player):
    document = player.read_text(encoding="utf-8")
    assert not re.search(r"<script[^>]+src=", document)
    assert not re.search(r"<link[^>]+href=", document)
    assert "__ROUTE_SCRIPT__" not in document and "__ROUTE_STYLE__" not in document


@pytest.mark.parametrize("name,width,height", VIEWPORTS)
def test_player_selftest_passes_in_a_real_browser(player, tmp_path, name, width, height):
    chrome = _chrome()
    if chrome is None:
        pytest.skip("Chrome 실행 파일이 없어 브라우저 자가 점검을 건너뜁니다.")
    dom, log = _run(chrome, player, tmp_path / f"profile-{name}", width, height)
    found = SELFTEST_RESULT.search(dom)
    assert found, f"{name}: 자가 점검 결과가 페이지에 없습니다. JS가 실행되지 않았는지 확인하세요."
    report = json.loads(found.group(1))
    assert report["failures"] == [], f"{name} 자가 점검 실패: {report['failures']}"
    assert report["checks"] > 0 and report["passed"] == report["checks"]
    assert report["results"] == 2
    assert "Uncaught" not in log, f"{name}: 브라우저 콘솔에 Uncaught 오류가 있습니다."
