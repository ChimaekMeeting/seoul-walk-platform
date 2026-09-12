"""실행 결과 폴더만 읽어 기록 불변식을 점검한다. 엔진을 다시 돌리지 않는다.

`python -m visualizations.routes`가 남긴 `trace.json`·`summary.json`·`routes.html`을
읽어 "기록이 스스로 모순되지 않는가"를 확인한다. 탐색을 다시 하지 않으므로 결과
폴더만 있으면 나중에도, 다른 자리에서도 같은 점검을 돌릴 수 있다.

```bash
python -m visualizations.checks outputs/algorithm_visualization/routes/sangmyung/<실행시각>
python -m visualizations.checks <결과 폴더> --artifact artifacts/walk_graph_v1.pkl
```

결과는 `<결과 폴더>/checks.json`에 쓰고, 위반이 하나라도 있으면 종료 코드 1이다.
`--artifact`를 주면 거리 수치를 실제 엣지 길이로 다시 재는 항목(E)까지 돌고, 없으면
그 항목만 "건너뜀"으로 기록한다.

`visualizations.routes`도 실행 끝에 이 점검을 부른다 — 위반이 있으면 `RuntimeError`로
멈추되 산출물은 지우지 않는다. 무엇이 어긋났는지 `checks.json`에서 봐야 하기 때문이다.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from visualizations.events import SERVICE_USE_VALUES, validate_events
from visualizations.route_view import describe_settings

# routes.html에 인라인된 payload를 꺼내는 자리. route_player.html의 태그와 같아야 한다.
PAYLOAD_PATTERN = re.compile(
    r'<script id="route-data" type="application/json">(.*?)</script>', re.S)
# 화면에 반드시 남아 있어야 하는 문구. 애니메이션 길이를 계산 시간으로 읽지 않게 한다.
TIMING_PHRASE = "계산 시간이 아닙니다"
# 실행 조건에 반드시 있어야 하는 항목.
REQUIRED_CONDITION_FIELDS = ("algorithm", "engine_class", "mode", "weight_policy", "service_use")
# 최종 경로에 남아 있어도 되는 노드를 만든 장면. 후보·기각·평가 장면은 여기 없다.
FINAL_SOURCE_KINDS = ("select", "route_changed", "cleanup", "final")
DISTANCE_TOLERANCE_M = 1e-6


class Report:
    """점검 하나의 결과. 위반 문장을 모아 두었다가 checks.json에 그대로 쓴다."""

    def __init__(self, name, title):
        self.name = name
        self.title = title
        self.violations = []
        self.skipped = None

    def fail(self, message):
        self.violations.append(message)

    def skip(self, reason):
        self.skipped = reason

    def as_dict(self):
        return {"name": self.name, "title": self.title,
                "passed": not self.violations, "skipped": self.skipped,
                "violations": self.violations}


class Context:
    """점검이 함께 읽는 입력. 결과 폴더 하나가 통째로 들어온다."""

    def __init__(self, folder, graph=None):
        self.folder = Path(folder)
        self.report = json.loads((self.folder / "trace.json").read_text(encoding="utf-8"))
        self.summary = json.loads((self.folder / "summary.json").read_text(encoding="utf-8"))
        self.html = (self.folder / "routes.html").read_text(encoding="utf-8")
        found = PAYLOAD_PATTERN.search(self.html)
        if not found:
            raise ValueError("routes.html에서 화면 payload를 찾지 못했습니다.")
        self.payload = json.loads(found.group(1))
        self.graph = graph

    @property
    def results(self):
        return self.report["results"]

    def where(self, result, event=None):
        """위반 문장 앞에 붙일 위치 표시."""
        if event is None:
            return result["mode"]
        return f"{result['mode']} {event.get('seq')}번 장면({event.get('phase')}/{event.get('kind')})"


# ── 후보 식별자 읽기 ─────────────────────────────────────────
def candidate_links(event):
    """이벤트가 가진 (후보 id, 부모 id, 노드열) 목록.

    Beam은 한 장면에 후보가 여럿이라 `values`의 병렬 목록으로 넣고, GRASP 계열은 장면
    하나가 후보 하나라 최상위 키에 넣는다. 두 형태를 같은 모양으로 읽는다.
    """
    values = event.get("values") or {}
    ids = values.get("candidate_ids")
    if isinstance(ids, list):
        parents = values.get("parent_candidate_ids") or [None] * len(ids)
        paths = event.get("paths") or []
        return [(ids[i], parents[i] if i < len(parents) else None,
                 paths[i] if i < len(paths) else None) for i in range(len(ids))]
    if event.get("candidate_id"):
        paths = event.get("paths") or []
        return [(event["candidate_id"], event.get("parent_candidate_id"),
                 paths[0] if paths else None)]
    return []


def _by_iteration(events, kind):
    """Beam 장면을 반복 번호로 묶는다. 반복 번호가 없는 기록은 빼고 본다."""
    grouped = {}
    for event in events:
        if event.get("kind") != kind:
            continue
        iteration = (event.get("values") or {}).get("iteration")
        if iteration is not None:
            grouped.setdefault(iteration, []).extend(
                tuple(path) for path in event.get("paths") or [])
    return grouped


def _path_distance(graph, nodes):
    """노드열을 실제 엣지 길이로 다시 잰다. 끊긴 노드열이면 None."""
    if len(nodes) < 2 or not all(graph.has_edge(a, b) for a, b in zip(nodes, nodes[1:])):
        return None
    return sum(float(graph[a][b]["length"]) for a, b in zip(nodes, nodes[1:]))


# ── 점검 ─────────────────────────────────────────────────────
def check_format(context, report):
    """A. 모든 기록이 공통 이벤트 형식을 만족하고 실행 조건이 갖춰져 있다."""
    for result in context.results:
        try:
            validate_events(result["trace"])
        except ValueError as exc:
            report.fail(f"{context.where(result)}: {exc}")
        conditions = result.get("conditions")
        if not conditions:
            report.fail(f"{context.where(result)}: conditions가 없습니다.")
            continue
        for field in REQUIRED_CONDITION_FIELDS:
            if not conditions.get(field):
                report.fail(f"{context.where(result)}: conditions.{field}가 비어 있습니다.")
        if conditions.get("service_use") not in SERVICE_USE_VALUES:
            report.fail(f"{context.where(result)}: 모르는 service_use "
                        f"{conditions.get('service_use')!r}.")
        if not (conditions.get("heuristic") or {}).get("name"):
            report.fail(f"{context.where(result)}: conditions.heuristic.name이 비어 있습니다.")


def check_order(context, report):
    """B. 단계 순서가 이어지고 Beam 반복 번호가 뒤로 가지 않는다."""
    for result in context.results:
        events = result["trace"]
        if not events:
            report.fail(f"{context.where(result)}: 기록이 비어 있습니다.")
            continue
        for i, event in enumerate(events):
            if event.get("seq") != i:
                report.fail(f"{context.where(result)}: {i}번째 이벤트의 seq가 {event.get('seq')!r}입니다.")
        if events[0].get("kind") != "run_start":
            report.fail(f"{context.where(result)}: 첫 kind가 {events[0].get('kind')!r}입니다.")
        if events[-1].get("kind") != "final":
            report.fail(f"{context.where(result)}: 마지막 kind가 {events[-1].get('kind')!r}입니다.")
        previous = None
        for event in events:
            iteration = (event.get("values") or {}).get("iteration")
            if iteration is None:
                continue
            if previous is not None and iteration < previous:
                report.fail(f"{context.where(result, event)}: 반복 번호가 {previous} → {iteration}로 줄었습니다.")
            previous = iteration
        expansions = [ (e.get("values") or {}).get("iteration") for e in events
                       if e.get("kind") == "candidates" and (e.get("values") or {}).get("iteration") is not None ]
        if expansions and expansions != sorted(set(expansions)):
            report.fail(f"{context.where(result)}: 확장 장면의 반복 번호가 1씩 늘지 않습니다({expansions[:8]}…).")


def check_candidate_links(context, report):
    """C. 부모 후보가 앞선 장면에 실제로 있고, Beam은 접두사 관계가 성립한다."""
    for result in context.results:
        seen = {}            # 후보 id → 노드열(있으면)
        restart_roots = set()  # 구축이 끝난 것으로 기록된 재시작 뿌리
        for event in result["trace"]:
            links = candidate_links(event)
            for identifier, parent, nodes in links:
                if parent is not None:
                    if parent not in seen:
                        report.fail(f"{context.where(result, event)}: 부모 후보 {parent!r}가 "
                                    "앞선 장면에 없습니다.")
                    elif nodes is not None and seen.get(parent):
                        prefix = seen[parent]
                        if len(prefix) >= len(nodes) or list(nodes[:len(prefix)]) != list(prefix):
                            report.fail(f"{context.where(result, event)}: 후보 {identifier!r}가 "
                                        f"부모 {parent!r}의 노드열로 시작하지 않습니다.")
                    if re.fullmatch(r"restart:\d+", parent) and parent not in restart_roots:
                        report.fail(f"{context.where(result, event)}: 재시작 뿌리 {parent!r}가 "
                                    "constructed·construction_failed 장면보다 먼저 쓰였습니다.")
            for identifier, _parent, nodes in links:
                seen.setdefault(identifier, list(nodes) if nodes else None)
            if event.get("phase") in ("constructed", "construction_failed") and event.get("candidate_id"):
                restart_roots.add(event["candidate_id"])


def check_reject_and_keep(context, report):
    """D. 같은 반복의 유지·탈락이 겹치지 않고 확장 후보를 정확히 나눈다."""
    for result in context.results:
        events = result["trace"]
        generated = _by_iteration(events, "candidates")
        kept = _by_iteration(events, "select")
        dropped = _by_iteration(events, "reject")
        for iteration, candidates in generated.items():
            keeps, drops = set(kept.get(iteration, [])), set(dropped.get(iteration, []))
            overlap = keeps & drops
            if overlap:
                report.fail(f"{context.where(result)} 반복 {iteration}: 유지와 탈락에 같은 후보가 "
                            f"{len(overlap)}개 있습니다.")
            if keeps | drops != set(candidates):
                report.fail(f"{context.where(result)} 반복 {iteration}: 유지∪탈락이 확장 후보와 "
                            f"다릅니다(확장 {len(set(candidates))}, 유지 {len(keeps)}, 탈락 {len(drops)}).")
        for event in events:
            # ALNS 내부 수락은 최종 채택이 아니다. 평가 장면 밖으로 올라가면 안 된다.
            if event.get("source_phase") == "alns_accept" and event.get("kind") != "evaluate":
                report.fail(f"{context.where(result, event)}: 내부 수락(alns_accept)이 "
                            f"{event.get('kind')!r}로 기록됐습니다.")


def check_stage_metrics(context, report):
    """E. 장면에 붙은 거리 수치가 실제 엣지 길이와 같다(그래프가 있어야 한다)."""
    if context.graph is None:
        report.skip("--artifact를 주지 않아 실제 엣지 길이로 다시 재지 않았습니다.")
        return
    for result in context.results:
        for event in result["trace"]:
            for key, nodes in (("stage_metrics", (event.get("paths") or [None])[0]),
                               ("before_metrics", event.get("before"))):
                metrics = event.get(key)
                if not metrics or not nodes:
                    continue
                measured = _path_distance(context.graph, nodes)
                if measured is None:
                    report.fail(f"{context.where(result, event)}: {key}가 있는데 노드열이 "
                                "실제 도보망에서 이어지지 않습니다.")
                elif abs(measured - metrics["distance_m"]) > DISTANCE_TOLERANCE_M:
                    report.fail(f"{context.where(result, event)}: {key}.distance_m "
                                f"{metrics['distance_m']} ≠ 다시 잰 값 {measured}.")


def check_final_route(context, report):
    """F. 최종 경로가 엔진 반환과 같고 중간 후보 노드가 섞이지 않는다."""
    for result in context.results:
        events = result["trace"]
        final = events[-1] if events else None
        if not final or final.get("kind") != "final":
            continue
        paths = final.get("paths") or []
        if not paths or list(paths[0]) != list(result["paths"][0] if result["paths"] else []):
            report.fail(f"{context.where(result)}: final 장면의 대표 경로가 반환 경로와 다릅니다.")
        responses = result.get("responses") or []
        if paths and responses:
            coordinates = responses[0].get("coordinates") or []
            if len(coordinates) != len(paths[0]):
                report.fail(f"{context.where(result)}: 응답 좌표 {len(coordinates)}개와 "
                            f"final 노드 {len(paths[0])}개가 다릅니다.")
        # 최종 경로의 노드는 골랐거나 실제로 바뀐 경로에서만 와야 한다. 확장·기각·평가
        # 장면에서만 보였던 노드가 섞이면 "버린 후보가 최종에 섞인" 것이다.
        allowed = {result["start"]["node"], result["end"]["node"]}
        for event in events:
            if event.get("kind") in FINAL_SOURCE_KINDS:
                for path in event.get("paths") or []:
                    allowed.update(path)
        for index, path in enumerate(paths):
            extra = sorted(set(path) - allowed)
            if extra:
                report.fail(f"{context.where(result)}: final paths[{index}]에 이전 장면에서 "
                            f"고른 적 없는 노드가 {len(extra)}개 섞였습니다(예: {extra[:5]}).")


def check_comparison_table(context, report):
    """G. 화면 비교표가 읽는 값이 summary.json과 같다."""
    summary_results = {r["mode"]: r for r in context.summary["results"]}
    payload_results = context.payload.get("results") or []
    if len(payload_results) != len(summary_results):
        report.fail(f"화면 결과 {len(payload_results)}개와 summary 결과 "
                    f"{len(summary_results)}개가 다릅니다.")
    for item in payload_results:
        stored = summary_results.get(item.get("mode"))
        if stored is None:
            report.fail(f"화면에 summary에 없는 결과 {item.get('mode')!r}가 있습니다.")
            continue
        if item.get("metrics") != stored.get("metrics"):
            report.fail(f"{stored['mode']}: 비교표 metrics가 summary와 다릅니다.")
        if item.get("run_seconds") != stored.get("run_seconds"):
            report.fail(f"{stored['mode']}: 비교표 run_seconds "
                        f"{item.get('run_seconds')!r} ≠ summary {stored.get('run_seconds')!r}.")
        if item.get("route_valid") != stored.get("route_valid"):
            report.fail(f"{stored['mode']}: 비교표 route_valid가 summary와 다릅니다.")
        expected = describe_settings(stored)
        if item.get("settings") != expected:
            report.fail(f"{stored['mode']}: 비교표 settings {item.get('settings')!r} ≠ "
                        f"실행 조건으로 다시 만든 {expected!r}.")


def check_recording_preserved(context, report):
    """H. 기록이 반환 결과를 바꾸지 않았고 입력이 보존됐다."""
    for key in ("graph_unchanged", "input_files_unchanged"):
        if context.summary.get(key) is not True:
            report.fail(f"summary.{key}가 {context.summary.get(key)!r}입니다.")
    for result in context.summary["results"]:
        for key in ("recording_preserves_result", "route_valid"):
            if result.get(key) is not True:
                report.fail(f"{result['mode']}: {key}가 {result.get(key)!r}입니다.")
        if result["mode"].startswith("shortest") and result.get("matches_dijkstra") is not True:
            report.fail(f"{result['mode']}: matches_dijkstra가 "
                        f"{result.get('matches_dijkstra')!r}입니다.")


def check_timing_separation(context, report):
    """I. 저장된 시간이 무계측 실행 값이고, 화면이 계산 시간과 구분해 적는다."""
    for result in context.summary["results"]:
        seconds = result.get("run_seconds")
        if seconds is None:
            report.fail(f"{result['mode']}: run_seconds가 없습니다(무계측 실행 값이어야 합니다).")
        elif not isinstance(seconds, (int, float)) or seconds <= 0:
            report.fail(f"{result['mode']}: run_seconds가 {seconds!r}입니다.")
    if TIMING_PHRASE not in context.html:
        report.fail(f"routes.html에 {TIMING_PHRASE!r} 문구가 없습니다.")


def check_landmarks_separated(context, report):
    """J. ALT 랜드마크가 경유지·도로 경로와 섞이지 않는다."""
    for result in context.results:
        landmarks = ((result.get("conditions") or {}).get("heuristic") or {}).get("landmarks") or []
        nodes = {item["node"] for item in landmarks}
        if not nodes:
            continue
        for event in result["trace"]:
            used = set(event.get("nodes") or [])
            for path in event.get("paths") or []:
                used.update(path)
            shared = sorted(nodes & used)
            if shared:
                report.fail(f"{context.where(result, event)}: 랜드마크 노드 {shared[:3]}가 "
                            "경로·노드 목록에 들어 있습니다.")


CHECKS = (
    ("A", "형식", check_format),
    ("B", "순서", check_order),
    ("C", "후보 연결", check_candidate_links),
    ("D", "기각·유지", check_reject_and_keep),
    ("E", "전후 수치", check_stage_metrics),
    ("F", "최종 경로", check_final_route),
    ("G", "비교표 일치", check_comparison_table),
    ("H", "기록 보존", check_recording_preserved),
    ("I", "시간 구분", check_timing_separation),
    ("J", "랜드마크 구분", check_landmarks_separated),
)


def run_checks(folder, graph=None, write=True):
    """결과 폴더 하나를 점검하고 `checks.json` 내용을 돌려준다.

    Args:
        folder: `trace.json`·`summary.json`·`routes.html`이 있는 실행 결과 폴더.
        graph: 있으면 거리 수치를 실제 엣지 길이로 다시 잰다(E 항목).
        write: True면 `<folder>/checks.json`을 쓴다.

    Returns:
        `{"passed", "folder", "checked_at_utc", "results", "checks": [...]}`.
    """
    context = Context(folder, graph=graph)
    reports = []
    for name, title, function in CHECKS:
        report = Report(name, title)
        function(context, report)
        reports.append(report)
    payload = {
        "folder": str(Path(folder)),
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": context.report.get("code_commit"),
        "results": len(context.results),
        "distance_recheck": graph is not None,
        "passed": all(not report.violations for report in reports),
        "checks": [report.as_dict() for report in reports],
    }
    if write:
        (Path(folder) / "checks.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def violation_summary(payload):
    """실패한 항목만 한 줄로 모은다. 예외 메시지와 종료 보고에 함께 쓴다."""
    return "; ".join(
        f"{check['name']}({check['title']}) {len(check['violations'])}건"
        for check in payload["checks"] if check["violations"])


def main():
    parser = argparse.ArgumentParser(
        description="실행 결과 폴더만 읽어 시각화 기록의 불변식을 점검합니다.")
    parser.add_argument("folder", help="trace.json·summary.json·routes.html이 있는 폴더")
    parser.add_argument("--artifact", help="거리 수치를 다시 재려면 도보망 artifact 경로")
    args = parser.parse_args()
    graph = None
    if args.artifact:
        from visualizations.graph_source import load_graph_artifact
        graph = load_graph_artifact(args.artifact).graph
    payload = run_checks(args.folder, graph=graph)
    for check in payload["checks"]:
        mark = "건너뜀" if check["skipped"] else ("통과" if check["passed"] else "실패")
        print(f"{check['name']} {check['title']}: {mark}"
              + (f" ({len(check['violations'])}건)" if check["violations"] else ""))
        for violation in check["violations"][:5]:
            print(f"    - {violation}")
        if len(check["violations"]) > 5:
            print(f"    … 그 밖 {len(check['violations']) - 5}건은 checks.json에 있습니다.")
    print(f"결과: {Path(args.folder) / 'checks.json'}")
    raise SystemExit(0 if payload["passed"] else 1)


if __name__ == "__main__":
    main()
