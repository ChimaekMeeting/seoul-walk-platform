"""
src/route_engine/weighted_cost_runtime.py

안전·편안 가중 비용의 **기동 시 1회** 준비와 그래프 부착(#445 6단계).

왜 요청마다 하지 않는가
-----------------------
WeightedEdgeCost.check_coverage()는 그래프 전체를 훑는 O(E) 연산이다. 실측
(2026-09-17, artifact 기준 엣지 223,693개)으로 약 0.30초가 든다. 요청마다 돌리면
같은 이슈에서 막 없앤 "요청당 전체 간선 순회"(compute_distance_only_lookup,
0.68~0.77초)를 절반쯤 되살리는 셈이다.

점수 적재 상태는 그래프가 바뀌기 전에는 변하지 않으므로 기동 때 한 번 계산해
G.graph에 붙여 두고, 요청은 그 결과(활성 여부 + 중앙값)만 읽어 자기 alpha/beta로
가벼운 WeightedEdgeCost를 만든다. alt_runtime.py가 ALT 거리표에 쓰는 것과 같은
prepare -> attach -> get 구조다.

요청 격리
---------
그래프에 붙이는 것은 **사용자와 무관한 데이터**(적재율·중앙값)뿐이다. alpha/beta는
붙이지 않는다 — 요청마다 다르고, 전역에 두면 다른 사용자의 가중치와 섞인다.

복구
----
WALK_WEIGHTED_COST_ENABLED=false로 재기동하면 준비를 건너뛰고 새 가중 연결을
거리 기준으로 처리한다. Beam의 기존 custom_score는 유지한다. 준비 실패나
커버리지 미달도 새 가중 연결을 비활성화한다.
"""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Optional, Sequence

import networkx as nx

from src.route_engine.scoring.weighted_edge_cost import (
    SCORE_ATTRS,
    CoverageReport,
    WeightedEdgeCost,
    normalize_preference_weights,
)

logger = logging.getLogger(__name__)

COVERAGE_KEY = "weighted_cost_coverage"


def prepare_weighted_cost(
    G: nx.Graph,
    *,
    enabled: bool,
    coverage_min_ratio: float,
) -> Optional[CoverageReport]:
    """점수 적재 상태를 한 번 계산한다. 비활성이거나 실패하면 None.

    Args:
        enabled: False면 아무것도 하지 않고 None을 돌려준다.
        coverage_min_ratio: 세 점수 각각이 이 비율 이상 적재돼 있어야 가중 모드를 켠다.

    Returns:
        CoverageReport 또는 None. None이면 호출자는 거리 전용으로 동작하면 된다.
        report.ok가 False인 경우도 None이 아니라 report를 돌려준다 — 왜 꺼졌는지
        진단할 수 있어야 하기 때문이다.
    """
    if not enabled:
        logger.info("가중 비용이 설정으로 비활성화돼 있습니다(WALK_WEIGHTED_COST_ENABLED=false).")
        return None

    started = perf_counter()
    try:
        report = WeightedEdgeCost.check_coverage(G, coverage_min_ratio)
    except Exception as exc:  # 기동을 막지 않는다 — 어떤 실패든 거리 전용으로 돌아간다.
        logger.warning(
            "가중 비용 준비에 실패해 거리 전용으로 폴백합니다: %s: %s",
            type(exc).__name__, exc,
        )
        return None

    elapsed = perf_counter() - started
    ratios = {attr: round(report.ratios.get(attr, 0.0), 4) for attr in SCORE_ATTRS}
    if report.ok:
        logger.info(
            "가중 비용 준비 완료: 적재율=%s, 기준=%.2f, %.3fs", ratios, coverage_min_ratio, elapsed,
        )
    else:
        logger.warning(
            "점수 커버리지가 기준에 못 미쳐 가중 비용을 끕니다(거리 전용으로 동작): "
            "미달 속성=%s, 적재율=%s, 기준=%.2f, %.3fs",
            report.missing_attrs(), ratios, coverage_min_ratio, elapsed,
        )
    return report


def attach_weighted_cost(G: nx.Graph, report: Optional[CoverageReport]) -> None:
    """준비한 적재 상태를 그래프에 붙인다.

    report가 None이면 이전에 붙어 있던 값을 지운다 — 같은 프로세스에서 다시
    초기화할 때 낡은 상태가 남지 않도록(attach_alt_heuristic과 같은 규칙).
    """
    if report is None:
        G.graph.pop(COVERAGE_KEY, None)
        return
    G.graph[COVERAGE_KEY] = report


def get_coverage_report(G: nx.Graph) -> Optional[CoverageReport]:
    """그래프에 붙은 점수 적재 상태. 없으면 None(가중 모드 불가)."""
    return G.graph.get(COVERAGE_KEY)


def build_request_cost_context(
    G: nx.Graph,
    *,
    safety_preference: float,
    slope_preference: float,
    weight_limit: float,
    accident_ratio: float,
    blocked_tags: Sequence[str] = (),
) -> Optional[WeightedEdgeCost]:
    """요청 하나가 쓸 WeightedEdgeCost를 만든다. 가중 모드가 불가하면 None.

    그래프를 훑지 않는다 — 기동 때 붙여 둔 적재율·중앙값만 읽는다. 요청당 비용은
    상수 시간이다.

    선호도(0~1)를 비용 계수로 바꾸는 일은 normalize_preference_weights()가 맡는다.
    두 선호도가 모두 0이면 비용이 정확히 length와 같아지므로(거리 전용과 동일)
    굳이 context를 만들지 않고 None을 돌려준다 — 호출부가 "가중 여부"를 하나의
    기준으로 판단할 수 있게 하기 위해서다.
    """
    report = get_coverage_report(G)
    if report is None or not report.ok:
        return None

    alpha, beta = normalize_preference_weights(
        safety=safety_preference, slope=slope_preference, weight_limit=weight_limit,
    )
    if alpha == 0.0 and beta == 0.0:
        return None

    return WeightedEdgeCost(
        alpha, beta,
        accident_ratio=accident_ratio,
        weight_limit=weight_limit,
        blocked_tags=blocked_tags,
        medians=report.medians,
        enabled=True,
    )
