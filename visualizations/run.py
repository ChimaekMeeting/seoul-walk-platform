"""오프라인 알고리즘 시각화 명령의 진입점."""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import networkx as nx

from visualizations.graph_source import load_graph_artifact
from visualizations.network_view import render_network_view


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"


def _validate_scenario_id(value: Any) -> str:
    reserved = {"CON", "PRN", "AUX", "NUL"} | {
        f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
    }
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value)
        or value.upper() in reserved
    ):
        raise ValueError("시나리오 id는 영문·숫자로 시작하는 영문·숫자·밑줄·하이픈 이름이어야 합니다. 예약 이름은 사용할 수 없습니다.")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="기존 Graph artifact로 ROUDI 도보망을 오프라인 시각화합니다."
    )
    parser.add_argument("--scenario", required=True, help="시나리오 이름(예: sangmyung) 또는 JSON 경로")
    parser.add_argument(
        "--network-only",
        action="store_true",
        help="도보망과 출발점 연결만 표시합니다. 현재 지원하는 실행 방식입니다.",
    )
    parser.add_argument(
        "--artifact",
        default=str(REPOSITORY_ROOT / "artifacts" / "walk_graph_v1.pkl"),
        help="Graph artifact .pkl 경로",
    )
    parser.add_argument(
        "--view-radius-m",
        type=float,
        default=2000.0,
        help="출발점을 중심으로 표시할 정사각형의 반폭(m), 기본 2000",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPOSITORY_ROOT / "outputs" / "algorithm_visualization"),
        help="실행 결과 루트 폴더",
    )
    return parser


def _scenario_path(value: str) -> Path:
    candidate = Path(value).expanduser()
    if candidate.suffix.lower() != ".json":
        candidate = SCENARIOS_DIR / f"{value}.json"
    elif not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    return candidate.resolve()


def _load_scenario(value: str) -> tuple[Path, dict[str, Any]]:
    path = _scenario_path(value)
    if not path.is_file():
        raise ValueError(f"시나리오 파일이 없습니다: {path}")
    try:
        scenario = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"시나리오 JSON을 읽을 수 없습니다: {exc}") from exc

    if not isinstance(scenario, dict):
        raise ValueError("시나리오 JSON은 객체여야 합니다.")
    scenario["id"] = _validate_scenario_id(scenario.get("id", path.stem))
    origin = scenario.get("origin")
    if not isinstance(origin, dict):
        raise ValueError("시나리오에 origin 객체가 필요합니다.")
    for key in ("lat", "lon", "coordinate_source_url", "verified_date"):
        if key not in origin:
            raise ValueError(f"시나리오 origin에 {key} 값이 필요합니다.")
    source_url = origin["coordinate_source_url"]
    if not isinstance(source_url, str) or not source_url.strip():
        raise ValueError("origin.coordinate_source_url은 비어 있지 않은 HTTP(S) URL이어야 합니다.")
    parsed_url = urlsplit(source_url)
    if parsed_url.scheme not in ("http", "https") or not parsed_url.hostname:
        raise ValueError("origin.coordinate_source_url은 HTTP(S) URL이어야 합니다.")
    verified_date = origin["verified_date"]
    try:
        if not isinstance(verified_date, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", verified_date):
            raise ValueError
        date.fromisoformat(verified_date)
    except ValueError as exc:
        raise ValueError("origin.verified_date는 유효한 YYYY-MM-DD 날짜여야 합니다.") from exc
    try:
        lat = float(origin["lat"])
        lon = float(origin["lon"])
    except (TypeError, ValueError) as exc:
        raise ValueError("origin.lat와 origin.lon은 숫자여야 합니다.") from exc
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError("origin 위도·경도가 유효 범위를 벗어났습니다.")
    return path, scenario


def _git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def _new_run_directory(root: Path, scenario_id: str) -> Path:
    scenario_id = _validate_scenario_id(scenario_id)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    output_root = root.expanduser().resolve()
    parent = output_root / scenario_id
    suffix = 0
    while True:
        run_name = timestamp if suffix == 0 else f"{timestamp}-{suffix:02d}"
        candidate = (parent / run_name).resolve()
        # 시나리오 폴더가 외부 경로로 연결된 경우도 파일 생성 전에 거부한다.
        if not candidate.is_relative_to(output_root):
            raise ValueError("실행 결과 경로가 지정한 출력 폴더를 벗어났습니다.")
        try:
            candidate.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            suffix += 1
            continue
        return candidate


def run(args: argparse.Namespace) -> Path:
    if not args.network_only:
        raise ValueError("현재는 --network-only 실행만 지원합니다.")
    if not math.isfinite(args.view_radius_m) or args.view_radius_m <= 0:
        raise ValueError("--view-radius-m은 0보다 큰 유한한 숫자여야 합니다.")

    scenario_path, scenario = _load_scenario(args.scenario)
    origin = scenario["origin"]
    source = load_graph_artifact(args.artifact)
    before_counts = (source.graph.number_of_nodes(), source.graph.number_of_edges())

    run_dir = _new_run_directory(Path(args.output_dir), scenario["id"])
    image_path = run_dir / "network.png"
    view = render_network_view(
        source.graph,
        origin_lat=float(origin["lat"]),
        origin_lon=float(origin["lon"]),
        view_radius_m=float(args.view_radius_m),
        output_path=image_path,
        data_version=str(source.manifest.get("data_version", "unknown")),
    )
    after_counts = (source.graph.number_of_nodes(), source.graph.number_of_edges())
    if after_counts != before_counts:
        raise RuntimeError("시각화 도중 입력 그래프의 노드·엣지 수가 변경되었습니다.")

    status = _git_value("status", "--porcelain", "--untracked-files=all")
    summary = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "code": {
            "commit": _git_value("rev-parse", "HEAD"),
            "worktree_changed": bool(status) if status is not None else None,
        },
        "graph_artifact": {
            "path": str(source.artifact_path),
            "data_version": source.manifest.get("data_version"),
            "source_commit": source.manifest.get("source_commit"),
            "sha256": source.manifest.get("artifact_sha256"),
            "node_count": before_counts[0],
            "edge_count": before_counts[1],
        },
        "runtime": {
            "python_version": platform.python_version(),
            "networkx_version": nx.__version__,
        },
        "scenario": {
            "id": scenario.get("id", scenario_path.stem),
            "name": scenario.get("name"),
            "path": str(scenario_path),
            "origin": origin,
        },
        "network_view": {
            "view_radius_m": float(args.view_radius_m),
            "zoom_radius_m": view.zoom_radius_m,
            "displayed_node_count": view.displayed_node_count,
            "displayed_edge_count": view.displayed_edge_count,
            "selected_node": {
                "id": view.selected_node_id,
                "lat": view.selected_node_lat,
                "lon": view.selected_node_lon,
                "connection_distance_m": view.connection_distance_m,
            },
        },
        "outputs": {"network_png": str(image_path.resolve())},
        "limitations": [
            "Graph artifact에는 도로의 상세 곡선 geometry가 없어 노드 사이를 직선으로 표시합니다.",
            "화면상의 선 길이는 실제 도보거리 계산에 사용하지 않습니다.",
        ],
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"데이터 버전: {source.manifest.get('data_version', 'unknown')}")
    print(f"전체 도보망: 노드 {before_counts[0]:,}개, 연결 {before_counts[1]:,}개")
    print(
        f"선택 노드: {view.selected_node_id} "
        f"({view.selected_node_lat:.6f}, {view.selected_node_lon:.6f})"
    )
    print(f"정문 입력점과 연결 거리: {view.connection_distance_m:.1f}m")
    if view.connection_distance_m > 30.0:
        print("주의: 연결 거리가 30m를 넘습니다. 확대 이미지를 확인해 주세요.")
    print(f"이미지: {image_path.resolve()}")
    print(f"실행 요약: {summary_path.resolve()}")
    return run_dir


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
