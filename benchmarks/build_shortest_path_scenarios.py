"""편도 점대점(A*/ALT) 벤치마크용 시나리오 데이터셋 생성기.

artifacts/walk_graph_v1.pkl의 실제 서울 도보망에서 seed 고정으로 (출발, 도착) 쌍을
뽑아 benchmarks/datasets/shortest_path.json을 만든다. 생성 스크립트와 JSON을 둘 다
커밋해 "어떤 쌍으로 쟀는지"가 실행마다 흔들리지 않게 한다.

구간(tier)을 나누는 이유: 휴리스틱의 효과는 탐색 거리에 따라 다르게 나타나고,
직선거리와 실제 도로거리가 크게 벌어지는 구간(한강·철도 횡단)에서는 Haversine
휴리스틱이 특히 약해진다. 그 구간을 따로 뽑아야 ALT와의 차이를 볼 수 있다.
same/unreachable은 성능이 아니라 경계 동작(즉시 종료 / 전체 소진)을 보기 위한 것이다.

출발 노드는 항상 최대 연결요소 안에서 고른다 — 실제 엔진의 PathUtils.find_nearest_node
와 landmark_shared._largest_component_nodes가 쓰는 것과 같은 규칙이다.

실행:
    python -m benchmarks.build_shortest_path_scenarios --seed 42
"""

import argparse
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import numpy as np

from benchmarks.config import DATASETS_DIR
from benchmarks.runner.test_oneway_shortest_path import distance_weight
from src.repository.network.graph_artifact_repository import GraphArtifactRepository
from src.route_engine.landmark_shared import _largest_component_nodes

_EARTH_R_M = 6371000.0

# tier별 선택 규칙. straight_m은 Haversine 직선거리(m), road_m은 distance_weight
# 기준 Dijkstra 최단거리(m)다. min_detour_ratio가 있으면 road_m/straight_m이 그 값
# 이상이어야 한다(우회가 강제되는 쌍만 남긴다).
TIER_RULES: dict[str, dict] = {
    "near": {
        "min_straight_m": 500.0,
        "max_straight_m": 1500.0,
        "min_detour_ratio": None,
        "count": 4,
    },
    "mid": {
        "min_straight_m": 3000.0,
        "max_straight_m": 5000.0,
        "min_detour_ratio": None,
        "count": 4,
    },
    "long": {
        "min_straight_m": 8000.0,
        "max_straight_m": 12000.0,
        "min_detour_ratio": None,
        "count": 4,
    },
    "detour": {
        "min_straight_m": 1000.0,
        "max_straight_m": 4000.0,
        "min_detour_ratio": 1.6,
        "count": 4,
    },
}


def detour_ratio(straight_m: float, road_m: float) -> float | None:
    """직선거리 대비 실제 도로거리 비율. 직선거리가 0 이하이면 정의되지 않아 None."""
    if straight_m <= 0:
        return None
    return road_m / straight_m


def qualifies(tier: str, straight_m: float, road_m: float | None) -> bool:
    """(straight_m, road_m) 쌍이 tier 규칙을 만족하는지.

    road_m이 None이면(도달 불가) 어떤 tier도 만족하지 않는다. 경계값은 포함한다
    (min <= straight <= max, ratio >= min_detour_ratio).
    """
    rule = TIER_RULES.get(tier)
    if rule is None:
        raise KeyError(f"알 수 없는 tier입니다: {tier}")
    if road_m is None:
        return False
    if not rule["min_straight_m"] <= straight_m <= rule["max_straight_m"]:
        return False
    if rule["min_detour_ratio"] is None:
        return True
    ratio = detour_ratio(straight_m, road_m)
    return ratio is not None and ratio >= rule["min_detour_ratio"]


def _haversine_vec(lat0: float, lon0: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """한 점에서 여러 노드까지의 Haversine 직선거리(m). PathUtils._haversine_m과 같은 공식."""
    phi1 = math.radians(lat0)
    phi2 = np.radians(lats)
    dphi = np.radians(lats - lat0)
    dlambda = np.radians(lons - lon0)
    a = np.sin(dphi / 2) ** 2 + math.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return _EARTH_R_M * 2 * np.arcsin(np.sqrt(a))


def _node_record(graph: nx.Graph, node: int) -> dict:
    data = graph.nodes[node]
    return {"node_id": int(node), "lat": float(data["lat"]), "lon": float(data["lon"])}


def build_scenarios(graph: nx.Graph, seed: int, max_starts: int) -> tuple[list[dict], dict]:
    """tier 규칙을 채울 때까지 무작위 출발 노드를 돌며 시나리오를 모은다.

    출발 노드 1개마다 SSSP를 1회만 돌리고, 그 결과로 아직 못 채운 tier들을 한 번에
    본다. 한 출발 노드에서 tier마다 최대 1쌍만 가져와 출발지가 한곳에 몰리지 않게 한다.

    Returns:
        (scenarios, notes) — notes에는 만들지 못한 tier와 그 이유가 담긴다.
    """
    rng = random.Random(seed)
    nodes = _largest_component_nodes(graph)
    order = sorted(int(n) for n in nodes)  # set 순회 순서에 의존하지 않도록 정렬 후 셔플
    rng.shuffle(order)

    index = np.array(order)
    lats = np.array([graph.nodes[n]["lat"] for n in order], dtype=float)
    lons = np.array([graph.nodes[n]["lon"] for n in order], dtype=float)

    remaining = {tier: rule["count"] for tier, rule in TIER_RULES.items()}
    scenarios: list[dict] = []
    starts_used = 0

    for start in order:
        if all(count == 0 for count in remaining.values()):
            break
        if starts_used >= max_starts:
            break
        starts_used += 1

        lengths = nx.single_source_dijkstra_path_length(graph, start, weight=distance_weight)
        road = np.array([lengths.get(n, math.inf) for n in order], dtype=float)
        straight = _haversine_vec(
            graph.nodes[start]["lat"], graph.nodes[start]["lon"], lats, lons
        )
        reachable = np.isfinite(road)

        for tier, rule in TIER_RULES.items():
            if remaining[tier] == 0:
                continue
            mask = (
                reachable
                & (straight >= rule["min_straight_m"])
                & (straight <= rule["max_straight_m"])
            )
            if rule["min_detour_ratio"] is not None:
                ratio = np.divide(road, straight, out=np.zeros_like(road), where=straight > 0)
                mask &= ratio >= rule["min_detour_ratio"]

            candidates = np.flatnonzero(mask)
            if candidates.size == 0:
                continue
            pos = int(rng.choice(candidates))
            end = int(index[pos])
            picked = rule["count"] - remaining[tier] + 1
            scenarios.append(
                {
                    "id": f"{tier}-{picked}",
                    "tier": tier,
                    "start": _node_record(graph, start),
                    "end": _node_record(graph, end),
                    "straight_m": float(straight[pos]),
                    "dijkstra_m": float(road[pos]),
                }
            )
            remaining[tier] -= 1

    unfilled = {tier: n for tier, n in remaining.items() if n > 0}
    if unfilled:
        raise RuntimeError(
            f"출발 노드 {starts_used}개를 봤지만 다음 tier를 채우지 못했습니다: {unfilled}. "
            "--max-starts를 늘리거나 TIER_RULES를 조정하세요."
        )

    # same: 출발 = 도착. 탐색이 즉시 끝나는지(거리 0, 확장 1회 이하) 확인용.
    same_node = int(rng.choice(order))
    scenarios.append(
        {
            "id": "same-1",
            "tier": "same",
            "start": _node_record(graph, same_node),
            "end": _node_record(graph, same_node),
            "straight_m": 0.0,
            "dijkstra_m": 0.0,
        }
    )

    # unreachable: 출발은 최대 연결요소, 도착은 다른 연결요소. 모든 방식이 연결요소를
    # 전부 소진하고 "경로 없음"으로 끝나야 한다.
    #
    # ⚠ 그래프가 완전 연결이면 이 쌍은 존재할 수 없다. 실제로 walk_graph_v1.pkl
    # (v2-2026-08-25)은 연결요소가 1개(전체 160,197노드)라 이 tier가 비어 나온다.
    # 이때 오류로 멈추지 않고 이유를 notes에 남긴다 — 나머지 tier의 측정까지 막을
    # 이유가 없고, "이 그래프에는 도달 불가 쌍이 없다" 자체가 기록할 사실이다.
    # 러너의 no_path 처리 경로는 tests/unit/test_alt_shortest_path_runner.py가
    # 고립 노드를 붙인 toy 그래프로 따로 검증한다.
    notes: dict[str, str] = {}
    components = sorted(nx.connected_components(graph), key=len, reverse=True)
    if len(components) < 2:
        notes["unreachable"] = (
            f"연결요소가 1개(노드 {len(components[0])}개)뿐이라 도달 불가 쌍을 만들 수 "
            "없어 이 tier는 비어 있습니다."
        )
        return scenarios, notes
    other = sorted(int(n) for n in components[1])
    unreachable_start = int(rng.choice(order))
    unreachable_end = int(rng.choice(other))
    ustart = graph.nodes[unreachable_start]
    uend = graph.nodes[unreachable_end]
    scenarios.append(
        {
            "id": "unreachable-1",
            "tier": "unreachable",
            "start": _node_record(graph, unreachable_start),
            "end": _node_record(graph, unreachable_end),
            "straight_m": float(
                _haversine_vec(
                    ustart["lat"],
                    ustart["lon"],
                    np.array([uend["lat"]]),
                    np.array([uend["lon"]]),
                )[0]
            ),
            "dijkstra_m": None,
        }
    )
    return scenarios, notes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", default="artifacts/walk_graph_v1.pkl")
    parser.add_argument("--data-version", default="v2-2026-08-25")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-starts",
        type=int,
        default=200,
        help="tier를 채우려고 시도할 출발 노드 수 상한(출발지마다 SSSP 1회).",
    )
    parser.add_argument("--out", default=str(DATASETS_DIR / "shortest_path.json"))
    args = parser.parse_args()

    graph = GraphArtifactRepository.load(
        args.artifact, expected_data_version=args.data_version
    )
    print(f"그래프 로드 완료: 노드 {graph.number_of_nodes()}개, 엣지 {graph.number_of_edges()}개")

    scenarios, notes = build_scenarios(graph, seed=args.seed, max_starts=args.max_starts)

    payload = {
        "meta": {
            "notes": notes,
            "seed": args.seed,
            "artifact": args.artifact,
            "data_version": args.data_version,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "graph_nodes": graph.number_of_nodes(),
            "graph_edges": graph.number_of_edges(),
            "weight": "benchmarks.runner.test_oneway_shortest_path.distance_weight "
            "(max(1.0, length) m)",
            "selection_rules": {
                "node_pool": "landmark_shared._largest_component_nodes(G) — 최대 연결요소만",
                "tiers": {
                    tier: {
                        "straight_m": [rule["min_straight_m"], rule["max_straight_m"]],
                        "min_detour_ratio": rule["min_detour_ratio"],
                        "count": rule["count"],
                    }
                    for tier, rule in TIER_RULES.items()
                },
                "same": "최대 연결요소에서 무작위 노드 1개, 출발 = 도착",
                "unreachable": "출발은 최대 연결요소, 도착은 두 번째로 큰 연결요소의 노드",
                "sampling": "seed 고정 random.Random. 출발 노드를 셔플해 순서대로 보며 "
                "출발지마다 SSSP 1회, tier마다 최대 1쌍씩 가져온다.",
            },
        },
        "scenarios": scenarios,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)

    print(f"시나리오 {len(scenarios)}개 저장: {out_path}")
    for tier, reason in notes.items():
        print(f"  [주의] tier '{tier}'를 만들지 못했습니다 — {reason}")
    for sc in scenarios:
        dij = "None" if sc["dijkstra_m"] is None else f"{sc['dijkstra_m']:.0f}m"
        ratio = (
            "-"
            if sc["dijkstra_m"] is None or sc["straight_m"] <= 0
            else f"{sc['dijkstra_m'] / sc['straight_m']:.2f}"
        )
        print(
            f"  [{sc['id']:>14}] {sc['tier']:<11} 직선 {sc['straight_m']:8.0f}m  "
            f"도로 {dij:>9}  비율 {ratio}"
        )


if __name__ == "__main__":
    main()
