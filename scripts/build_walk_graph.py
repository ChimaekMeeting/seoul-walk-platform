from __future__ import annotations

import argparse
import logging
import subprocess
import time
from pathlib import Path

from src.config.settings import settings
from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.repository.network.graph_repository import GraphRepository
from src.route_engine.scoring.scoring_engine import WeightedEdgeCost


logger = logging.getLogger(__name__)

# 세 점수 각각이 이 비율 이상 적재돼 있어야 artifact를 저장한다. src/config/settings.py의
# WALK_SCORE_COVERAGE_MIN(런타임 게이트 기준)과 같은 값을 쓴다 — 이 스크립트가 만든
# artifact가 그 게이트를 넘지 못하면 서비스·벤치마크 양쪽에서 조용히 거리 전용으로
# 폴백하므로, 만드는 시점에 같은 기준으로 미리 막는다.
_MIN_SCORE_COVERAGE = 0.95


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
        default=settings.WALK_GRAPH_DATA_VERSION,
        help="manifest에 기록할 데이터 기준 버전. 기본값은 settings.WALK_GRAPH_DATA_VERSION"
             "(서비스가 검증에 쓰는 값과 항상 같다) — 새 버전을 배포하려면 여기서 값을 "
             "명시하고, 서비스에 반영할 때 settings 쪽 기본값도 같이 올릴 것.",
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

    # 점수가 비어있는 DB(예: 로컬 seoul_walk)로 빌드하면 이 확인 없이는 artifact가
    # 그대로 저장되고, 그 문제가 fixture·서비스 전체로 조용히 퍼진다(#474). 여기서 막아
    # "artifact가 존재한다 = 점수가 실려 있다"를 보장한다.
    coverage = WeightedEdgeCost.check_coverage(graph, _MIN_SCORE_COVERAGE)
    if not coverage.ok:
        raise SystemExit(
            "점수 커버리지가 기준에 못 미쳐 artifact를 저장하지 않습니다: "
            f"기준={_MIN_SCORE_COVERAGE:.2f}, 미달 속성={coverage.missing_attrs()}, "
            f"적재율={ {attr: round(ratio, 4) for attr, ratio in coverage.ratios.items()} }. "
            "점수가 적재된 DB로 다시 실행하세요."
        )
    logger.info(
        "점수 커버리지 확인 완료: 기준=%.2f, 적재율=%s",
        _MIN_SCORE_COVERAGE,
        {attr: round(ratio, 4) for attr, ratio in coverage.ratios.items()},
    )

    manifest = GraphArtifactRepository.save(
        graph,
        args.output,
        data_version=args.data_version,
        source_commit=source_commit,
        source_dirty=source_dirty,
        score_coverage={attr: round(ratio, 4) for attr, ratio in coverage.ratios.items()},
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
