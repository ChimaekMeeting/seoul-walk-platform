# src/route_engine/engines/oneway_bi_astar.py
import heapq
from itertools import count
from typing import Callable

import networkx as nx

from src.route_engine.engines.oneway_astar import OnewayAstarEngine

logger = __import__("logging").getLogger(__name__)


def _bidirectional_astar_path(
    G: nx.Graph,
    source: int,
    target: int,
    heuristic: Callable[[int, int], float],
    weight: Callable[[int, int, dict], float],
):
    """
    일관된 이중 potential(pf/pr)을 이용한 양방향 A*.
    G는 무방향 그래프라고 가정 — 역방향 탐색도 동일한 인접 구조를 사용.
    weight는 networkx 관례와 동일한 콜러블(u, v, edge_data) -> float.
    """
    if source == target:
        return [source], 0.0

    def pf(v: int) -> float:
        return (heuristic(v, target) - heuristic(source, v)) / 2

    def pr(v: int) -> float:
        return -pf(v)

    push, pop, c = heapq.heappush, heapq.heappop, count()

    dists  = [{}, {}]
    seen   = [{source: 0.0}, {target: 0.0}]
    paths  = [{source: [source]}, {target: [target]}]
    fringe = [[], []]
    push(fringe[0], (pf(source), next(c), source))
    push(fringe[1], (pr(target), next(c), target))

    finalpath, finaldist = [], float("inf")
    dir_ = 1
    while fringe[0] and fringe[1]:
        dir_ = 1 - dir_
        _, _, v = pop(fringe[dir_])
        if v in dists[dir_]:
            continue
        dists[dir_][v] = seen[dir_][v]

        if finaldist < float("inf") and fringe[0] and fringe[1]:
            if fringe[0][0][0] + fringe[1][0][0] >= finaldist:
                break

        for w, edata in G[v].items():
            if w in dists[dir_]:
                continue
            vw_len = seen[dir_][v] + weight(v, w, edata)
            if w not in seen[dir_] or vw_len < seen[dir_][w]:
                seen[dir_][w] = vw_len
                priority = vw_len + (pf(w) if dir_ == 0 else pr(w))
                push(fringe[dir_], (priority, next(c), w))
                paths[dir_][w] = paths[dir_][v] + [w]

                if w in seen[0] and w in seen[1]:
                    total = seen[0][w] + seen[1][w]
                    if total < finaldist:
                        finaldist = total
                        finalpath = paths[0][w][:-1] + list(reversed(paths[1][w]))

    if finaldist == float("inf"):
        raise nx.NetworkXNoPath(f"No path between {source} and {target}.")
    return finalpath, finaldist


class OnewayBidirectionalAstarEngine(OnewayAstarEngine):
    """OnewayAstarEngine과 동일한 인터페이스, 탐색만 양방향 A*로 교체."""

    def find_path(self, start: int, end: int) -> list[int]:
        try:
            path, _ = _bidirectional_astar_path(
                self.G, start, end,
                heuristic=self._heuristic,
                weight=self._weight_fn,
            )
            return path
        except nx.NetworkXNoPath:
            logger.warning("출발-도착 노드 사이에 연결된 경로가 없습니다")
            return []
        except Exception:
            logger.exception("최단 경로 생성에 실패했습니다")
            return []
