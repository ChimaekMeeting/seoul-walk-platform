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

원본과 달라진 점은 다음 네 가지뿐이며 탐색 순서·결과 경로는 원본과 동일하다.
  1. heappop/heappush 횟수를 센다.
  2. 성공 시 (path, popped, pushed)를 반환한다.
  3. 경로가 없을 때 원본과 똑같이 nx.NetworkXNoPath를 올리되, 예외 객체에
     popped/pushed 속성을 붙여 실패한 탐색의 계산량도 기록할 수 있게 했다.
  4. 선택 인자 observer로 pop/push/skip 시점을 밖에 알린다. observer=None(기본)이면
     호출 자체가 없어 동작·반환값·시간 측정이 지금과 완전히 같다. 시각화 어댑터가
     이 훅으로 단계별 이벤트를 만든다(visualizations/astar_adapter.py).

⚠ networkx를 올릴 때는 원본 astar_path()와 이 파일을 다시 대조해야 한다. 원본이
바뀌면 이 복제본은 조용히 다른 알고리즘이 된다.
"""

from heapq import heappop, heappush
from itertools import count

import networkx as nx
from networkx.algorithms.shortest_paths.weighted import _weight_function


def astar_path_instrumented(
    G, source, target, heuristic=None, weight="weight", *, cutoff=None, observer=None
) -> tuple[list, int, int]:
    """nx.astar_path와 같은 경로를 반환하면서 큐 통계를 함께 돌려준다.

    Args:
        observer: None이면 아무 일도 하지 않는다(기본, 기존 동작 그대로). 주면 아래
            세 시점을 알려 준다. 탐색 결과에는 영향을 주지 않는다.

            - ``on_pop(node, g, parent, explored, queue)``: 큐에서 꺼낸 직후
              (popped를 센 직후, 도착 판정 전).
            - ``on_push(node, g, h, f, parent, reason)``: 큐에 넣은 직후.
              reason은 ``"new"``(처음 넣음) 또는 ``"improved"``(더 나은 비용으로 갱신).
            - ``on_skip(node, reason)``: 건너뛴 항목. reason은 ``"blocked"``(비용
              None), ``"stale"``(이미 더 나은 경로로 확장한 항목을 꺼냄),
              ``"worse"``(이미 같거나 더 나은 비용이 큐에 있음), ``"cutoff"``.

            ⚠ ``explored``와 ``queue``는 **읽기 전용**으로 넘긴다. 관찰자가 이 두
            자료구조를 수정하면 탐색이 달라진다 — 읽기만 해야 한다.

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
        if observer is not None:
            observer.on_pop(curnode, dist, parent, explored, queue)

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
                if observer is not None:
                    observer.on_skip(curnode, "stale")
                continue

            # Skip bad paths that were enqueued before finding a better one
            qcost, h = enqueued[curnode]
            if qcost < dist:
                if observer is not None:
                    observer.on_skip(curnode, "stale")
                continue

        explored[curnode] = parent

        for neighbor, w in G_succ[curnode].items():
            cost = weight(curnode, neighbor, w)
            if cost is None:
                if observer is not None:
                    observer.on_skip(neighbor, "blocked")
                continue
            ncost = dist + cost
            if neighbor in enqueued:
                qcost, h = enqueued[neighbor]
                # if qcost <= ncost, a less costly path from the
                # neighbor to the source was already determined.
                # Therefore, we won't attempt to push this neighbor
                # to the queue
                if qcost <= ncost:
                    if observer is not None:
                        observer.on_skip(neighbor, "worse")
                    continue
                push_reason = "improved"
            else:
                h = heuristic(neighbor, target)
                push_reason = "new"

            if cutoff and ncost + h > cutoff:
                if observer is not None:
                    observer.on_skip(neighbor, "cutoff")
                continue

            enqueued[neighbor] = ncost, h
            heappush(queue, (ncost + h, next(c), neighbor, ncost, curnode))
            pushed += 1
            if observer is not None:
                observer.on_push(neighbor, ncost, h, ncost + h, curnode, push_reason)

    error = nx.NetworkXNoPath(f"Node {target} not reachable from {source}")
    error.popped = popped
    error.pushed = pushed
    raise error
