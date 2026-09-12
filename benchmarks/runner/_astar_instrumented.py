"""nx.astar_path를 복제해 큐 통계(popped/pushed)를 함께 돌려주는 계측판.

NetworkX는 탐색이 노드를 몇 개나 확장했는지 밖으로 내주지 않는다. 휴리스틱 품질을
비교하려면 "시간"만으로는 부족하다 — 시간은 머신 상태에 흔들리지만 확장 노드 수는
같은 입력에서 결정적이라, 휴리스틱이 탐색 공간을 실제로 얼마나 줄였는지를 직접
보여준다. 그래서 알고리즘을 그대로 베끼고 카운터만 더했다.

복제 원본: networkx 3.6, networkx/algorithms/shortest_paths/astar.py 의 astar_path().
원본 라이선스: NetworkX는 3-Clause BSD License(BSD-3-Clause)로 배포된다.
  Copyright (C) 2004-2025, NetworkX Developers
  Aric Hagberg <hagberg@lanl.gov>, Dan Schult <dschult@colgate.edu>,
  Pieter Swart <swart@lanl.gov>
  전문: https://github.com/networkx/networkx/blob/main/LICENSE.txt

원본과 달라진 점은 다음 세 가지뿐이며 탐색 순서·결과 경로는 원본과 동일하다.
  1. heappop/heappush 횟수를 센다.
  2. 성공 시 (path, popped, pushed)를 반환한다.
  3. 경로가 없을 때 원본과 똑같이 nx.NetworkXNoPath를 올리되, 예외 객체에
     popped/pushed 속성을 붙여 실패한 탐색의 계산량도 기록할 수 있게 했다.

⚠ networkx를 올릴 때는 원본 astar_path()와 이 파일을 다시 대조해야 한다. 원본이
바뀌면 이 복제본은 조용히 다른 알고리즘이 된다.
"""

from heapq import heappop, heappush
from itertools import count

import networkx as nx
from networkx.algorithms.shortest_paths.weighted import _weight_function


def astar_path_instrumented(
    G, source, target, heuristic=None, weight="weight", *, cutoff=None
) -> tuple[list, int, int]:
    """nx.astar_path와 같은 경로를 반환하면서 큐 통계를 함께 돌려준다.

    Returns:
        (path, popped, pushed)
        - popped: 우선순위 큐에서 꺼낸 횟수. 같은 노드가 더 나은 경로로 다시
          들어왔다가 꺼내지면 중복해서 센다(원본 알고리즘이 실제로 하는 일 그대로).
        - pushed: 큐에 넣은 횟수. 시작 노드를 큐에 올리는 최초 1회를 포함한다.

    Raises:
        nx.NodeNotFound: source나 target이 그래프에 없을 때(원본과 동일).
        nx.NetworkXNoPath: 경로가 없을 때(원본과 동일). 이 구현은 예외 객체에
            popped/pushed 속성을 붙여 보낸다 — 도달 불가 탐색의 계산량을 기록하기
            위해서이며, 예외 종류와 메시지는 원본과 같다.
    """
    if source not in G:
        raise nx.NodeNotFound(f"Source {source} is not in G")

    if target not in G:
        raise nx.NodeNotFound(f"Target {target} is not in G")

    if heuristic is None:
        # The default heuristic is h=0 - same as Dijkstra's algorithm
        def heuristic(u, v):
            return 0

    weight = _weight_function(G, weight)

    G_succ = G._adj

    c = count()
    queue = [(0, next(c), source, 0, None)]
    popped = 0
    pushed = 1  # 시작 노드를 큐에 올린 최초 1회

    enqueued = {}
    explored = {}

    while queue:
        _, __, curnode, dist, parent = heappop(queue)
        popped += 1

        if curnode == target:
            path = [curnode]
            node = parent
            while node is not None:
                path.append(node)
                node = explored[node]
            path.reverse()
            return path, popped, pushed

        if curnode in explored:
            # Do not override the parent of starting node
            if explored[curnode] is None:
                continue

            # Skip bad paths that were enqueued before finding a better one
            qcost, h = enqueued[curnode]
            if qcost < dist:
                continue

        explored[curnode] = parent

        for neighbor, w in G_succ[curnode].items():
            cost = weight(curnode, neighbor, w)
            if cost is None:
                continue
            ncost = dist + cost
            if neighbor in enqueued:
                qcost, h = enqueued[neighbor]
                # if qcost <= ncost, a less costly path from the
                # neighbor to the source was already determined.
                # Therefore, we won't attempt to push this neighbor
                # to the queue
                if qcost <= ncost:
                    continue
            else:
                h = heuristic(neighbor, target)

            if cutoff and ncost + h > cutoff:
                continue

            enqueued[neighbor] = ncost, h
            heappush(queue, (ncost + h, next(c), neighbor, ncost, curnode))
            pushed += 1

    error = nx.NetworkXNoPath(f"Node {target} not reachable from {source}")
    error.popped = popped
    error.pushed = pushed
    raise error
