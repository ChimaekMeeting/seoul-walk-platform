import math
import random

import networkx as nx


class PathUtils:
    def __init__(self, G: nx.Graph):
        self.G = G

    def find_nearest_node(self, lat: float, lon: float) -> int | None:
        """위경도 → 가장 가까운 그래프 노드 ID"""
        min_dist = float("inf")
        nearest  = None
        for node_id, data in self.G.nodes(data=True):
            node_lat = data.get("lat")
            node_lon = data.get("lon")
            if node_lat is None or node_lon is None:
                continue
            dist = math.sqrt((lat - node_lat) ** 2 + (lon - node_lon) ** 2)
            if dist < min_dist:
                min_dist = dist
                nearest  = node_id
        return nearest

    def extract_coordinates(self, node_list: list) -> list:
        """노드 ID 리스트 → [[lat, lon], ...] 변환"""
        return [
            [self.G.nodes[n]["lat"], self.G.nodes[n]["lon"]]
            for n in node_list
            if n in self.G.nodes
        ]

    def prune_dead_ends(self, path_nodes: list, max_branch_length: float = 400.0) -> list:
        """
        왕복 가지치기: 같은 노드가 두 번 등장하는 구간 중
        짧은 것(max_branch_length 미만)을 제거
        """
        pruned  = list(path_nodes)
        changed = True
        while changed:
            changed        = False
            node_positions = {}
            candidates     = []
            for i, node in enumerate(pruned):
                if node in node_positions:
                    first = node_positions[node]
                    branch_length = sum(
                        (self.G.get_edge_data(pruned[j], pruned[j + 1]) or {}).get("length", 0)
                        for j in range(first, i)
                    )
                    if branch_length < max_branch_length:
                        candidates.append((branch_length, first, i))
                else:
                    node_positions[node] = i
            if candidates:
                _, first, last = min(candidates, key=lambda x: x[0])
                pruned  = pruned[:first + 1] + pruned[last + 1:]
                changed = True
        return pruned

    def remove_dead_ends(self) -> nx.Graph:
        """막힌 끝 노드(degree=1)를 반복 제거한 새 그래프를 반환합니다."""
        G = self.G.copy()
        while True:
            dead_ends = [n for n, d in G.degree() if d == 1]
            if not dead_ends:
                break
            G.remove_nodes_from(dead_ends)
        return G

    def circular_random_walk(self, start_node: int, target_km: float = 3.0) -> list[int]:
        """
        pre-weighted 그래프에서 확률적 랜덤 워크로 순환 경로 노드 목록을 반환합니다.
        custom_score 엣지 속성이 계산된 그래프를 받아야 합니다.
        """
        target_m   = target_km * 1000
        path_nodes = [start_node]
        total_dist = 0.0
        current    = start_node
        visited: dict = {}
        sx = self.G.nodes[start_node].get("lon", 0)
        sy = self.G.nodes[start_node].get("lat", 0)

        while total_dist < target_m * 0.75:
            neighbors = list(self.G.neighbors(current))
            if not neighbors:
                break

            probs = []
            for n in neighbors:
                ek         = tuple(sorted([current, n]))
                visit_pen  = 1.0 / (1 + visited.get(ek, 0) * 7)
                degree_pen = 1.0 / (1 + max(0, 3 - self.G.degree(n)))
                score      = (self.G.get_edge_data(current, n) or {}).get("custom_score", 1.0)

                if total_dist / target_m < 0.7:
                    dx    = self.G.nodes[n].get("lon", 0) - sx
                    dy    = self.G.nodes[n].get("lat", 0) - sy
                    dist  = (dx ** 2 + dy ** 2) ** 0.5
                    score = score / ((dist + 1e-6) ** 2)

                probs.append((1.0 / (score + 1e-6)) * visit_pen * degree_pen)

            total_p = sum(probs)
            if total_p == 0:
                break

            next_node   = random.choices(neighbors, weights=[p / total_p for p in probs], k=1)[0]
            ek          = tuple(sorted([current, next_node]))
            visited[ek] = visited.get(ek, 0) + 1
            total_dist += (self.G.get_edge_data(current, next_node) or {}).get("length", 0)
            path_nodes.append(next_node)
            current = next_node

        # 출발 노드 복귀
        if path_nodes[-1] != start_node:
            try:
                def _return_w(u, v, d):
                    ek = tuple(sorted([u, v]))
                    return d.get("length", 1.0) * (1 + visited.get(ek, 0) * 10)

                return_path = nx.shortest_path(self.G, path_nodes[-1], start_node, weight=_return_w)
                path_nodes += return_path[1:]
            except nx.NetworkXNoPath:
                pass

        return path_nodes

    def oneway_waypoint_path(self, start: int, end: int, target_km: float = 3.0) -> list[int]:
        """
        경유 노드를 통해 우회 편도 경로 노드 목록을 반환합니다.
        custom_score 엣지 속성이 계산된 그래프를 받아야 합니다.
        """
        target_m = target_km * 1000
        p1       = self.G.nodes[start]
        p2       = self.G.nodes[end]

        candidates = []
        for node, data in self.G.nodes(data=True):
            if node in (start, end):
                continue
            d1    = math.sqrt((data.get("lon", 0) - p1.get("lon", 0)) ** 2 + (data.get("lat", 0) - p1.get("lat", 0)) ** 2) * 111000
            d2    = math.sqrt((data.get("lon", 0) - p2.get("lon", 0)) ** 2 + (data.get("lat", 0) - p2.get("lat", 0)) ** 2) * 111000
            total = d1 + d2
            if target_m * 0.6 <= total <= target_m * 0.9:
                candidates.append((node, abs(total - target_m * 0.8)))

        if not candidates:
            mid_lat  = (p1.get("lat", 0) + p2.get("lat", 0)) / 2 + 0.005
            mid_lon  = (p1.get("lon", 0) + p2.get("lon", 0)) / 2 + 0.005
            waypoint = self.find_nearest_node(mid_lat, mid_lon)
        else:
            candidates.sort(key=lambda x: x[1])
            waypoint = random.choice(candidates[:5])[0]

        try:
            path1 = nx.shortest_path(self.G, start, waypoint, weight="custom_score")

            saved = {}  # 1구간 재사용 억제
            for i in range(len(path1) - 1):
                u, v = path1[i], path1[i + 1]
                if self.G.has_edge(u, v):
                    saved[(u, v)]            = self.G[u][v]["custom_score"]
                    self.G[u][v]["custom_score"] *= 100

            try:
                path2 = nx.shortest_path(self.G, waypoint, end, weight="custom_score")
            finally:
                for (u, v), w in saved.items():  # 페널티 복원 보장
                    self.G[u][v]["custom_score"] = w

            return path1[:-1] + path2

        except Exception:
            try:
                return nx.shortest_path(self.G, start, end, weight="custom_score")
            except Exception:
                return []
