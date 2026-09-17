"""
src/route_engine/scoring/weighted_edge_cost.py

안전·편안 선호를 도로 길이에 얹는 요청 단위 탐색 비용 계산기(#445 1단계).

scoring_engine.py의 custom_score와 무엇이 다른가
------------------------------------------------
custom_score는 8축 가중치를 곱·나눗셈으로 블렌딩하는 **할인 모델**이라 비용이
length보다 작아질 수 있다. 그래서 A*가 최적성을 유지하려면 휴리스틱을
min_cost_length_ratio()로 축소해야 한다(path_utils.astar_path(min_ratio=...)).

이 모듈은 **페널티 전용 모델**이다.

    cost = length * (1 + alpha * unsafe + beta * discomfort)

alpha, beta, unsafe, discomfort가 모두 0 이상이므로 항상 `cost >= length`가
성립한다. 덕분에 기동 때 length로 만들어 둔 ALT Planar 거리표(alt_runtime.py)를
사용자 가중치가 바뀌어도 다시 만들지 않고 그대로 admissible heuristic으로 쓸 수
있다. 이 불변식이 이 모듈의 존재 이유이므로 수식을 바꿀 때 가장 먼저 확인한다.

또 하나의 차이는 전체 간선 lookup을 만들지 않는다는 점이다.
compute_distance_only_lookup()은 호출마다 2*E 크기 dict를 새로 만들지만
weight()는 A*가 실제로 확인한 edge_data에서 곧바로 계산한다.

책임 경계
---------
이 계산기는 Weights(8축 선호도)를 모른다. 챗봇·설문이 만든 0~1 선호도를
비용 계수 alpha/beta로 바꾸는 일은 normalize_preference_weights()가 맡는다.
가중치 산출 로직이 바뀌어도 비용 수식이 흔들리지 않게 하기 위한 분리다.

이 모듈이 결정하지 않는 것
--------------------------
- accident_ratio(lambda): 안전시설 부족과 사고위험을 섞는 비율. 서비스 의미에
  해당하므로 기본값을 두지 않고 호출자가 반드시 넘긴다.
- weight_limit(k): alpha+beta 상한. 마찬가지로 호출자가 넘긴다.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from typing import Mapping, Sequence

import networkx as nx

from src.route_engine.waypoint_route_builder import MissingEdgeAttributeError

logger = logging.getLogger(__name__)

_LENGTH_ATTR = "length"  # waypoint_route_builder._LENGTH_ATTR와 동일 기준

# unsafe/discomfort 계산에 필요한 edge 속성. 커버리지 게이트도 이 목록만 본다.
SAFETY_ATTR = "safety_score"      # 클수록 안전 -> 결핍은 (1 - safety_score)
ACCIDENT_ATTR = "accident_score"  # 클수록 위험 -> 그대로 사용
SLOPE_ATTR = "slope_score"        # 클수록 평탄 -> 불편은 (1 - slope_score)

SCORE_ATTRS: tuple[str, ...] = (SAFETY_ATTR, ACCIDENT_ATTR, SLOPE_ATTR)


@dataclass(frozen=True)
class CoverageReport:
    """그래프 한 개에 대한 점수 적재 상태. WeightedEdgeCost.check_coverage()가 만든다.

    ratios : 속성별 "값이 있고 None이 아닌" edge 비율(0~1)
    medians: 속성별 중앙값. NULL 대체에 쓴다(값이 하나도 없으면 키 자체가 없다).
    ok     : 모든 속성이 min_ratio 이상인가. 가중 모드 활성화 여부를 이 값으로 정한다.
    """

    ratios: Mapping[str, float]
    medians: Mapping[str, float]
    min_ratio: float
    ok: bool

    def missing_attrs(self) -> list[str]:
        """min_ratio에 미달한 속성명(적재율이 낮은 순)."""
        return sorted(
            (attr for attr, ratio in self.ratios.items() if ratio < self.min_ratio),
            key=lambda attr: self.ratios[attr],
        )


def normalize_preference_weights(
    safety: float,
    slope: float,
    weight_limit: float,
) -> tuple[float, float]:
    """0~1 선호도(Weights.safety / Weights.slope)를 비용 계수 (alpha, beta)로 바꾼다.

    선호도와 비용 계수는 의미가 다르다 — 전자는 "얼마나 원하는가", 후자는 "그
    도로의 탐색 비용을 몇 배까지 올릴 것인가"다. 그래서 그대로 쓰지 않고 합이
    weight_limit을 넘지 않도록 비례 축소한다(둘의 상대 비율은 보존).

    합이 상한 이내면 값을 그대로 돌려준다. 따라서 safety=slope=0이면 (0.0, 0.0)이
    되어 비용이 정확히 length와 같아진다(거리 전용 동작).
    """
    if weight_limit <= 0:
        raise ValueError(f"weight_limit은 양수여야 합니다: {weight_limit!r}")
    for name, value in (("safety", safety), ("slope", slope)):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} 선호도는 0~1이어야 합니다: {value!r}")

    total = safety + slope
    if total <= weight_limit:
        return float(safety), float(slope)

    scale = weight_limit / total
    return safety * scale, slope * scale


class WeightedEdgeCost:
    """요청 하나 동안 고정되는 탐색 비용 계산기.

    nx.astar_path / nx.dijkstra의 `weight=` 콜러블로 그대로 넘긴다. 요청마다 한 번
    만들고 그 요청의 모든 구간·후보가 같은 인스턴스를 공유한다 — 사용자별 가중치가
    서로 섞이지 않도록 전역에 보관하지 않는다.

    생성 후 alpha/beta/accident_ratio를 바꾸지 않는다(탐색 도중 비용이 달라지면
    A*의 최적성 근거가 무너진다). median_substitutions만 진단용으로 누적한다.
    """

    def __init__(
        self,
        alpha: float,
        beta: float,
        *,
        accident_ratio: float,
        weight_limit: float,
        blocked_tags: Sequence[str] = (),
        medians: Mapping[str, float] | None = None,
        enabled: bool = True,
    ):
        if weight_limit <= 0:
            raise ValueError(f"weight_limit은 양수여야 합니다: {weight_limit!r}")
        if alpha < 0 or beta < 0:
            raise ValueError(f"alpha/beta는 음수일 수 없습니다: alpha={alpha!r}, beta={beta!r}")
        if alpha + beta > weight_limit:
            raise ValueError(
                f"alpha+beta가 상한을 넘습니다: {alpha!r}+{beta!r} > {weight_limit!r}"
            )
        if not 0.0 <= accident_ratio <= 1.0:
            raise ValueError(f"accident_ratio는 0~1이어야 합니다: {accident_ratio!r}")

        self.alpha = float(alpha)
        self.beta = float(beta)
        self.accident_ratio = float(accident_ratio)
        self.weight_limit = float(weight_limit)
        self.blocked_tags = tuple(blocked_tags)
        self.medians: Mapping[str, float] = dict(medians or {})
        self.enabled = bool(enabled)
        self.median_substitutions = 0

    # ── 생성 ─────────────────────────────────────────────────────────────

    @classmethod
    def check_coverage(cls, G: nx.Graph, min_ratio: float) -> CoverageReport:
        """그래프 전체에서 점수 속성의 적재율과 중앙값을 한 번에 계산한다.

        edge마다 판단하지 않고 그래프 단위로 한 번만 보는 이유: 누락된 점수를
        edge마다 0으로 대체하면 "점수가 없는 도로 = 가장 안전한 도로"가 되어
        안전 가중치를 올릴수록 데이터 없는 길로 몰리는 정반대 효과가 난다.
        """
        if not 0.0 <= min_ratio <= 1.0:
            raise ValueError(f"min_ratio는 0~1이어야 합니다: {min_ratio!r}")

        total = G.number_of_edges()
        values: dict[str, list[float]] = {attr: [] for attr in SCORE_ATTRS}
        for _, _, data in G.edges(data=True):
            for attr in SCORE_ATTRS:
                value = data.get(attr)
                if value is not None:
                    values[attr].append(float(value))

        ratios = {
            attr: (len(found) / total if total else 0.0)
            for attr, found in values.items()
        }
        medians = {
            attr: statistics.median(found)
            for attr, found in values.items()
            if found
        }
        return CoverageReport(
            ratios=ratios,
            medians=medians,
            min_ratio=min_ratio,
            ok=bool(total) and all(ratio >= min_ratio for ratio in ratios.values()),
        )

    @classmethod
    def from_graph(
        cls,
        G: nx.Graph,
        alpha: float,
        beta: float,
        *,
        accident_ratio: float,
        weight_limit: float,
        coverage_min_ratio: float,
        blocked_tags: Sequence[str] = (),
    ) -> "WeightedEdgeCost":
        """커버리지 게이트를 돌려 가중 모드 활성화 여부까지 정해 인스턴스를 만든다.

        게이트 판정은 여기서 로그로 한 번만 남긴다 — weight()는 A* 핫패스라
        로그도 할당도 두지 않는다.
        """
        report = cls.check_coverage(G, coverage_min_ratio)
        if not report.ok:
            logger.warning(
                "점수 커버리지 미달로 가중 비용을 비활성화합니다(거리 전용으로 동작): "
                "기준=%.2f, 미달 속성=%s, 적재율=%s",
                coverage_min_ratio,
                report.missing_attrs(),
                {attr: round(ratio, 4) for attr, ratio in report.ratios.items()},
            )
        else:
            logger.info(
                "가중 비용을 활성화합니다: alpha=%.4f, beta=%.4f, accident_ratio=%.4f, 적재율=%s",
                alpha, beta, accident_ratio,
                {attr: round(ratio, 4) for attr, ratio in report.ratios.items()},
            )

        return cls(
            alpha, beta,
            accident_ratio=accident_ratio,
            weight_limit=weight_limit,
            blocked_tags=blocked_tags,
            medians=report.medians,
            enabled=report.ok,
        )

    # ── 비용 ─────────────────────────────────────────────────────────────

    def unsafe(self, edge_data: Mapping) -> float:
        """0~1. 클수록 피해야 하는 도로.

        accident_ratio(lambda)가 안전시설 부족과 사고위험의 결합 비율이다.
        """
        safety = self._score(edge_data, SAFETY_ATTR)
        accident = self._score(edge_data, ACCIDENT_ATTR)
        return self.accident_ratio * (1.0 - safety) + (1.0 - self.accident_ratio) * accident

    def discomfort(self, edge_data: Mapping) -> float:
        """0~1. 클수록 불편한(경사가 심한) 도로."""
        return 1.0 - self._score(edge_data, SLOPE_ATTR)

    def weight(self, u, v, edge_data: Mapping) -> float:
        """nx.astar_path/nx.dijkstra의 weight= 콜러블.

        입력 edge_data를 변경하지 않는다. 차단 태그는 inf, 가중 모드가 꺼져 있으면
        거리 그대로를 돌려준다.
        """
        length = self._length(u, v, edge_data)

        if self.blocked_tags:
            tags = edge_data.get("tags") or ()
            if any(tag in tags for tag in self.blocked_tags):
                return float("inf")

        if not self.enabled:
            return length

        multiplier = 1.0 + self.alpha * self.unsafe(edge_data) + self.beta * self.discomfort(edge_data)
        return length * multiplier

    # ── 내부 ─────────────────────────────────────────────────────────────

    def _length(self, u, v, edge_data: Mapping) -> float:
        if _LENGTH_ATTR not in edge_data:
            raise MissingEdgeAttributeError(
                f"엣지 ({u}, {v})에 '{_LENGTH_ATTR}' 속성이 없습니다: {edge_data!r}"
            )
        length = edge_data[_LENGTH_ATTR]
        if length is None or length <= 0:
            raise ValueError(f"엣지 ({u}, {v})의 length는 양수여야 합니다: {length!r}")
        return float(length)

    def _score(self, edge_data: Mapping, attr: str) -> float:
        """점수 하나를 0~1로 읽는다. 없거나 None이면 커버리지 게이트가 계산한
        중앙값으로 대체하고, 중앙값조차 없으면 예외를 던진다 — 0으로 조용히
        대체하면 "데이터 없는 도로가 가장 좋은 도로"가 되기 때문이다."""
        value = edge_data.get(attr)
        if value is None:
            median = self.medians.get(attr)
            if median is None:
                raise MissingEdgeAttributeError(
                    f"엣지에 '{attr}' 값이 없고 대체할 중앙값도 없습니다: {dict(edge_data)!r}"
                )
            self.median_substitutions += 1
            return median

        value = float(value)
        if not 0.0 <= value <= 1.0:
            raise ValueError(
                f"'{attr}'는 0~1이어야 합니다: {value!r} (edge={dict(edge_data)!r})"
            )
        return value

    def __repr__(self) -> str:  # 로그·테스트 실패 메시지 가독성용
        return (
            f"WeightedEdgeCost(alpha={self.alpha:.4f}, beta={self.beta:.4f}, "
            f"accident_ratio={self.accident_ratio:.4f}, enabled={self.enabled})"
        )
