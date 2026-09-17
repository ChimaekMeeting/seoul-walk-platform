"""
src/route_engine/scoring/detour_cap.py

가중 경로가 물리 최단경로 대비 얼마나 돌아가는지를 제한하는 순수 함수(#445).

왜 엔진 안이 아니라 별도 함수인가
---------------------------------
1. OnewayAstarEngine.find_path()는 벤치마크 solver가 직접 호출한다. 엔진 내부에서
   상한을 적용하면 solver가 재는 값이 조용히 달라진다.
2. 상한은 leg가 아니라 **요청 전체**의 성질이다. leg마다 독립 적용하면 5구간 경로가
   허용치를 5배까지 넘길 수 있다. 요청을 소유한 쪽(RouteService, WaypointComposerEngine)이
   완성된 경로에 한 번 적용해야 한다.

비교 기준은 탐색 비용이 아니라 **실제 이동 거리(length 합)**다. 가중 비용은 단위가
사용자 가중치에 따라 달라져 "얼마나 돌아갔는가"를 나타내지 못한다.

상한 값(max_ratio)은 이 모듈이 정하지 않는다. alpha+beta 상한(엣지 비용 증가 폭)과는
다른 설정이므로 같은 값으로 묶지 않는다 — 호출자가 넘긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import networkx as nx

from src.route_engine.errors import MissingEdgeAttributeError

_LENGTH_ATTR = "length"


@dataclass(frozen=True)
class DetourDecision:
    """상한 판정 결과. 진단 로그·벤치마크에 그대로 실을 수 있게 수치를 남긴다."""

    path: list[int]
    capped: bool                    # True면 물리 최단으로 되돌린 것
    weighted_distance_m: float
    physical_distance_m: float
    max_ratio: float
    # 비교 기준 경로가 있어 상한을 실제로 검증했는가. 기준 경로를 만들지 못하면
    # 가중 경로를 그대로 쓰되 여기를 False로 남긴다 — "상한 이내"와 "확인 못 함"을
    # 같은 것으로 보고하면 안 된다.
    verified: bool = True

    @property
    def detour_ratio(self) -> float:
        """가중 경로가 물리 최단보다 얼마나 더 긴가(0.0 = 동일). 기준 거리가 0이면 0."""
        if self.physical_distance_m <= 0:
            return 0.0
        return self.weighted_distance_m / self.physical_distance_m - 1.0


def path_distance_m(G: nx.Graph, path: Sequence[int]) -> float:
    """노드열의 실제 이동 거리(m). 탐색 비용이 아니라 length 합이다."""
    total = 0.0
    for u, v in zip(path, path[1:]):
        data = G[u][v]
        if _LENGTH_ATTR not in data:
            raise MissingEdgeAttributeError(
                f"엣지 ({u}, {v})에 '{_LENGTH_ATTR}' 속성이 없습니다: {data!r}"
            )
        total += float(data[_LENGTH_ATTR])
    return total


def apply_detour_cap(
    G: nx.Graph,
    weighted_path: Optional[Sequence[int]],
    physical_path: Optional[Sequence[int]],
    max_ratio: float,
) -> DetourDecision:
    """가중 경로의 실제 거리가 물리 최단 × (1 + max_ratio)를 넘으면 물리 최단으로 되돌린다.

    재탐색하지 않는다 — 가중치를 줄여가며 여러 번 다시 찾으면 A* 호출 수가 요청마다
    달라져 예측이 안 된다. 호출자는 두 경로를 이미 갖고 있으므로 비교 한 번이면 된다.

    둘 중 하나가 없으면 있는 쪽을 그대로 돌려준다(capped=False).
    """
    if max_ratio < 0:
        raise ValueError(f"max_ratio는 음수일 수 없습니다: {max_ratio!r}")

    if not weighted_path:
        physical = list(physical_path or [])
        distance = path_distance_m(G, physical) if len(physical) > 1 else 0.0
        return DetourDecision(physical, False, distance, distance, max_ratio, verified=True)

    weighted = list(weighted_path)
    weighted_distance = path_distance_m(G, weighted) if len(weighted) > 1 else 0.0

    if not physical_path:
        # 비교할 기준이 없으므로 가중 경로를 그대로 쓰되 검증하지 못했음을 남긴다.
        return DetourDecision(
            weighted, False, weighted_distance, 0.0, max_ratio, verified=False,
        )

    physical = list(physical_path)
    physical_distance = path_distance_m(G, physical) if len(physical) > 1 else 0.0

    if physical_distance <= 0:
        return DetourDecision(
            weighted, False, weighted_distance, physical_distance, max_ratio, verified=False,
        )

    # 경계값(정확히 상한)은 초과가 아니다 — `>`이지 `>=`가 아니다.
    if weighted_distance > physical_distance * (1.0 + max_ratio):
        return DetourDecision(
            physical, True, weighted_distance, physical_distance, max_ratio, verified=True,
        )

    return DetourDecision(
        weighted, False, weighted_distance, physical_distance, max_ratio, verified=True,
    )
