from __future__ import annotations

import argparse
import logging
import subprocess
import time
from pathlib import Path

from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.repository.network.graph_repository import GraphRepository


logger = logging.getLogger(__name__)


def _git_state() -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
        return commit, dirty
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"Git 기준 커밋을 확인할 수 없습니다: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="현재 PostgreSQL 도보망으로 배포용 NetworkX Graph를 빌드합니다."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/walk_graph_v1.pkl"),
        help="생성할 .pkl 경로",
    )
    parser.add_argument(
        "--data-version",
        default="v1-2026-07-30",
        help="manifest에 기록할 데이터 기준 버전",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="로컬 검증용으로만 미커밋 코드에서 빌드를 허용합니다.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="[%(levelname)s] [%(name)s] %(message)s",
    )

    source_commit, source_dirty = _git_state()
    if source_dirty and not args.allow_dirty:
        raise SystemExit(
            "작업 트리에 미커밋 변경이 있습니다. 최종 배포 artifact는 코드를 "
            "커밋한 뒤 빌드하세요. 로컬 검증만 할 때는 --allow-dirty를 사용합니다."
        )

    started_at = time.perf_counter()
    logger.info("PostgreSQL에서 최종 서비스 Graph를 생성합니다.")
    graph = GraphRepository.load_graph()
    manifest = GraphArtifactRepository.save(
        graph,
        args.output,
        data_version=args.data_version,
        source_commit=source_commit,
        source_dirty=source_dirty,
    )
    loaded_graph = GraphArtifactRepository.load(
        args.output,
        allow_dirty=args.allow_dirty,
    )
    if (
        loaded_graph.number_of_nodes() != graph.number_of_nodes()
        or loaded_graph.number_of_edges() != graph.number_of_edges()
    ):
        raise SystemExit("저장 후 재로드한 Graph 건수가 원본과 다릅니다.")
    elapsed = time.perf_counter() - started_at

    artifact, manifest_path, checksum_path = (
        GraphArtifactRepository.companion_paths(args.output)
    )
    logger.info(
        "Graph artifact 빌드 완료: nodes=%s, edges=%s, size=%.1f MiB, elapsed=%.1fs",
        manifest["node_count"],
        manifest["edge_count"],
        manifest["artifact_size_bytes"] / 1024 / 1024,
        elapsed,
    )
    logger.info("artifact: %s", artifact.resolve())
    logger.info("manifest: %s", manifest_path.resolve())
    logger.info("checksum: %s", checksum_path.resolve())


if __name__ == "__main__":
    main()
