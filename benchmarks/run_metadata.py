"""
benchmarks/run_metadata.py

실행 산출물(CSV) 옆에 재현 메타데이터를 남긴다(2026-09-10 신규, 이슈 J).

지금까지 벤치마크 CSV에는 숫자만 있고 "언제, 어떤 코드로, 어떤 그래프 위에서, 어떤
파라미터로" 잰 값인지가 전혀 남지 않았다. AGENTS.md는 실행 수치에 확인 날짜·환경·재현
위치를 함께 적도록 요구하고, 이 벤치마크의 목적 자체가 "실험값을 실측으로 확정"하는
것이므로 이 정보 없이는 산출물이 근거가 되지 못한다.

형식은 benchmarks/runner/waypoint_overlap_audit.py가 이미 쓰던 metadata.json을 따른다
(python/networkx 버전, 그래프 규모, 핵심 소스의 code_sha256, 시드 목록, 하이퍼파라미터).
다만 그 모듈은 저장 시 "x" 모드로 덮어쓰기를 거부하는데, 격자 러너는 같은 CSV를 반복
실행하는 것이 정상이므로 여기서는 덮어쓴다 — 대신 CSV와 메타데이터가 항상 같은 실행의
짝이 되도록 CSV를 쓴 직후에만 저장한다.

주의: 여기 담기는 git SHA는 "이 실행 시점의 HEAD"이지 "이 결과를 만든 코드"라는 보증이
아니다. dirty=True면 커밋되지 않은 변경이 섞여 있으므로 그 CSV는 재현 근거로 쓰지 말 것.
"""

import hashlib
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from benchmarks.config import ROUTE_EDGES_PARQUET, ROUTE_NODES_PARQUET

_ROOT = Path(__file__).resolve().parents[1]

# 결과를 좌우하는 핵심 소스. 이 파일들이 바뀌면 같은 파라미터라도 다른 수치가 나온다.
_TRACKED_SOURCES = (
    "benchmarks/results.py",
    "benchmarks/config.py",
    "src/route_engine/engines/grasp_waypoint_common.py",
    "src/route_engine/engines/waypoint_refinement.py",
    "src/route_engine/engines/waypoint_construction.py",
    "src/route_engine/waypoint_route_builder.py",
    "src/route_engine/waypoint_alns.py",
    "src/route_engine/waypoint_beam.py",
)


def _digest(path: Path) -> str | None:
    """파일 내용의 SHA256. 없으면 None(그래프 fixture 미빌드 등)."""
    if not path.exists():
        return None
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _git(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args], cwd=_ROOT, capture_output=True, text=True, timeout=10, check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def _git_state() -> dict:
    """커밋 SHA와 작업 트리 오염 여부.

    dirty=True인 실행 결과는 어떤 코드가 그 수치를 만들었는지 특정할 수 없다 —
    재현 근거로 쓰려면 커밋 후 다시 돌려야 한다.
    """
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    return {
        "commit": commit,
        "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": bool(status) if status is not None else None,
    }


def _package_versions() -> dict:
    versions = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("pandas", "networkx", "numpy"):
        try:
            versions[name] = __import__(name).__version__
        except Exception:
            versions[name] = None
    return versions


def collect_metadata(runner: str, **extra) -> dict:
    """이번 실행을 재현하는 데 필요한 정보를 모은다.

    extra에는 러너가 아는 격자·파라미터를 그대로 넣는다(seeds, target_kms, start_nodes,
    algos, workers, timeout_sec, 스윕 노브 등). 담기는 값이 많을수록 좋다 — 나중에
    "왜 이 수치가 나왔는지"를 되짚을 때 빠진 축 하나가 분석을 막는다.
    """
    return {
        "runner": runner,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git": _git_state(),
        "environment": _package_versions(),
        "graph_fixture": {
            "nodes_parquet_sha256": _digest(ROUTE_NODES_PARQUET),
            "edges_parquet_sha256": _digest(ROUTE_EDGES_PARQUET),
        },
        "code_sha256": {path: _digest(_ROOT / path) for path in _TRACKED_SOURCES},
        "run": extra,
    }


def metadata_path_for(csv_path) -> Path:
    """CSV 옆에 나란히 둘 메타데이터 경로. results.csv -> results.metadata.json"""
    return Path(csv_path).with_suffix(".metadata.json")


def save_run_metadata(csv_path, runner: str, **extra) -> Path:
    """CSV를 쓴 직후에 호출한다. 반환값은 저장된 메타데이터 경로."""
    target = metadata_path_for(csv_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = collect_metadata(runner, **extra)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)

    if payload["git"]["dirty"]:
        print(
            "[경고] 커밋되지 않은 변경이 있는 상태로 실행됐습니다 — 이 CSV는 어떤 코드가 만든 "
            "수치인지 특정할 수 없으므로 재현 근거로 쓰지 마세요.",
            file=sys.stderr,
        )
    return target
