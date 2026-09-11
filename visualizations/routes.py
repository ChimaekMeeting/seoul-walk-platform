"""python -m visualizations.routes --scenario sangmyung"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import networkx as nx

from visualizations.graph_source import load_graph_artifact
from visualizations.route_experiment import compare_recording, execute, graph_digest, snap, validate_lengths
from visualizations.route_view import write_route_views
from visualizations.route_story import prepare_story
from visualizations.run import REPOSITORY_ROOT, _git_value, _load_scenario, _new_run_directory


def validate_destination(location):
    if not isinstance(location, dict):
        raise ValueError("시나리오에 destination 좌표·출처가 필요합니다.")
    try:
        lat, lon = float(location["lat"]), float(location["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
        source = urlsplit(location["coordinate_source_url"])
        if source.scheme not in ("http", "https") or not source.hostname:
            raise ValueError
        checked = location["verified_date"]
        if date.fromisoformat(checked).isoformat() != checked:
            raise ValueError
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("destination의 위경도·HTTP(S) 출처·YYYY-MM-DD 확인일을 확인하세요.") from exc
    return {**location, "lat": lat, "lon": lon}


def run_suite(args):
    if args.grasp_iterations < 1:
        raise ValueError("grasp_iterations는 1 이상이어야 합니다.")
    for name in ("target_km", "detour_extra_km"):
        if not math.isfinite(getattr(args, name)) or getattr(args, name) <= 0:
            raise ValueError(f"{name}는 0보다 큰 유한한 숫자여야 합니다.")
    _, scenario = _load_scenario(args.scenario)
    destination = validate_destination(scenario.get("destination"))
    source = load_graph_artifact(args.artifact)
    graph = source.graph
    validate_lengths(graph)
    fingerprint = graph_digest(graph)
    input_hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (source.artifact_path, source.manifest_path, source.checksum_path)}
    start, end = snap(graph, scenario["origin"]), snap(graph, destination)
    shortest_m = nx.dijkstra_path_length(graph, start["node"], end["node"], weight="length")
    if shortest_m <= 0:
        raise ValueError("출발점과 도착점이 같은 도보망 노드입니다. 편도 테스트 지점을 바꾸세요.")
    detour_m = shortest_m + args.detour_extra_km * 1000
    results = []
    cases = [("shortest", end, None), ("detour", end, detour_m), ("circular", start, args.target_km * 1000)]
    if args.with_grasp:
        cases += [(f"grasp_{r}", start, args.target_km * 1000) for r in ("none", "local", "vnd", "vns", "alns")]
    for mode, finish, target in cases:
        print(f"{mode}: 실제 엔진 실행 및 탐색 기록", flush=True)
        recorded = execute(graph, mode, start, finish, target, grasp_iterations=args.grasp_iterations, seed=args.seed)
        plain = execute(graph, mode, start, finish, target, record=False, grasp_iterations=args.grasp_iterations, seed=args.seed)
        recorded["recording_preserves_result"] = compare_recording(recorded, plain)
        recorded["run_seconds"] = plain["run_seconds"]
        recorded["trace"].insert(0, {"phase": "start", "paths": [[start["node"]]]})
        if mode == "shortest":
            recorded["dijkstra_distance_m"] = shortest_m
            recorded["matches_dijkstra"] = bool(recorded["metrics"]) and math.isclose(
                recorded["metrics"][0]["distance_m"], shortest_m, abs_tol=1e-6)
            if not recorded["matches_dijkstra"]:
                raise RuntimeError("A* 경로 거리가 Dijkstra 기준값과 다릅니다.")
        recorded["route_valid"] = bool(recorded["metrics"]) and all(
            m["connected"] and m["endpoints_match"] for m in recorded["metrics"])
        prepare_story(graph, recorded)
        results.append(recorded)
        print(f"  경로 거리(m): {[round(m['distance_m'], 1) for m in recorded['metrics']]}", flush=True)
    unchanged = graph_digest(graph) == fingerprint
    unchanged_files = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest
                          for p, digest in input_hashes.items())
    if not unchanged or not unchanged_files:
        raise RuntimeError("입력 도보망 보존 검증에 실패했습니다.")
    output = _new_run_directory(Path(args.output_dir), scenario["id"])
    report = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "code_commit": _git_value("rev-parse", "HEAD"),
        "worktree_status": _git_value("status", "--short"),
        "runtime": {"python": platform.python_version(), "networkx": nx.__version__},
        "timing_policy": "One untraced engine.run wall-clock measurement after traced run; excludes artifact loading, graph deepcopy, engine construction, trace setup, validation and rendering; includes run preprocessing and response creation. Not a repeated benchmark.",
        "scenario": scenario, "artifact_manifest": source.manifest,
        "artifact_path": str(source.artifact_path), "input_hashes": input_hashes,
        "graph_unchanged": unchanged, "input_files_unchanged": unchanged_files,
        "cost_policy": "base edge cost = length; preference vector = distance; existing revisit penalty and pruning retained",
        "detour_extra_km": args.detour_extra_km,
        "intent_cases": [
            {"request": "상명대에서 경복궁역 3번 출입구까지 최단거리", "result": "shortest"},
            {"request": "상명대에서 경복궁역 3번 출입구까지 우회", "result": "detour"},
            {"request": f"상명대에서 {args.target_km:g}km 순환", "result": "circular"},
            {"request": f"상명대에서 그냥 {args.target_km:g}km 걷고 싶어", "result": "circular",
             "verification": "existing prompt rule mapping only; no LLM invocation"},
        ],
        "results": results,
    }
    if args.with_grasp:
        for r in results[3:]:
            report["intent_cases"].append({"request": f"{args.target_km:g}km 순환 · {r['engine']}", "result": r["mode"]})
    (output / "trace.json").write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
    write_route_views(graph, report, output)
    summary = {**report, "results": [{k: v for k, v in r.items() if k not in ("trace", "responses")}
                                    for r in results]}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"재생 화면: {output / 'routes.html'}\n최종 경로 그림: {output / 'routes.png'}", flush=True)
    return output


def main():
    parser = argparse.ArgumentParser(description="기존 A*·Beam 탐색을 거리 기반 조건으로 기록하고 재생합니다.")
    parser.add_argument("--scenario", default="sangmyung")
    parser.add_argument("--artifact", default=str(REPOSITORY_ROOT / "artifacts/walk_graph_v1.pkl"))
    parser.add_argument("--target-km", type=float, default=3.0, help="순환 목표 거리")
    parser.add_argument("--with-grasp", action="store_true", help="GRASP 구축 및 Local/VND/VNS/ALNS 비교 추가")
    parser.add_argument("--grasp-iterations", type=int, default=4, help="시각화 예제 재시작 횟수(기존 엔진 기본은 24)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--detour-extra-km", type=float, default=1.0, help="편도 목표 = 측정한 최단거리 + 이 거리")
    parser.add_argument("--output-dir", default=str(REPOSITORY_ROOT / "outputs/algorithm_visualization/routes"))
    args = parser.parse_args()
    try:
        run_suite(args)
    except Exception as exc:
        parser.exit(1, f"오류: {exc}\n")


if __name__ == "__main__":
    main()
