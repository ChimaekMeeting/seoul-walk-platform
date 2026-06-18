import math
import random

import networkx as nx


class PathUtils:
    def __init__(self, G: nx.Graph):
        self.G = G

    def find_nearest_node(self, lat: float, lon: float) -> int | None:
        """
        위경도에서 그래프상 가장 가까운 노드 ID를 반환합니다.
        """
        min_dist = float("inf")  # 최솟값 초기화
        nearest  = None          # 최근접 노드 ID
        for node_id, data in self.G.nodes(data=True):
            node_lat = data.get("lat")
            node_lon = data.get("lon")
            if node_lat is None or node_lon is None:  # 좌표 없는 노드 스킵
                continue
            dist = math.sqrt((lat - node_lat) ** 2 + (lon - node_lon) ** 2)  # 유클리드 거리
            if dist < min_dist:  # 더 가까운 노드 갱신
                min_dist = dist
                nearest  = node_id
        return nearest

    def extract_coordinates(self, node_list: list) -> list:
        """
        노드 ID 리스트를 [[lat, lon], ...] 좌표 리스트로 변환합니다.
        """
        coords = []
        for n in node_list:
            if n not in self.G.nodes:
                continue
            lat = self.G.nodes[n].get("lat")
            lon = self.G.nodes[n].get("lon")
            # Some graph nodes can be incomplete in DB snapshots; skip them
            # instead of crashing the whole route response.
            if lat is None or lon is None:
                continue
            coords.append([lat, lon])
        return coords

    def prune_dead_ends(self, path_nodes: list, max_branch_length: float = 400.0) -> list:
        """
        왕복 가지치기를 수행합니다.
        같은 노드가 두 번 등장하는 구간 중 max_branch_length 미만인 것을 반복 제거합니다.
        """
        pruned  = list(path_nodes)
        changed = True
        while changed:
            changed        = False
            node_positions = {}   # 노드별 첫 등장 인덱스
            candidates     = []   # 제거 후보 (branch_length, 시작, 끝)
            for i, node in enumerate(pruned):
                if node in node_positions:
                    first = node_positions[node]  # 이전 등장 위치
                    branch_length = sum(
                        (self.G.get_edge_data(pruned[j], pruned[j + 1]) or {}).get("length", 0)
                        for j in range(first, i)
                    )  # 왕복 구간 길이
                    if branch_length < max_branch_length:
                        candidates.append((branch_length, first, i))
                else:
                    node_positions[node] = i
            if candidates:
                _, first, last = min(candidates, key=lambda x: x[0])  # 가장 짧은 가지 선택
                pruned  = pruned[:first + 1] + pruned[last + 1:]       # 해당 구간 제거
                changed = True
        return pruned

    def remove_dead_ends(self) -> nx.Graph:
        """
        degree=1인 막힌 끝 노드를 반복 제거한 새 그래프를 반환합니다.
        """
        G = self.G.copy()
        while True:
            dead_ends = [n for n, d in G.degree() if d == 1]  # 연결 엣지가 1개뿐인 노드
            if not dead_ends:
                break
            G.remove_nodes_from(dead_ends)
        return G

    def calc_distance(self, nodes: list[int]) -> float:
        """
        노드 목록의 총 이동 거리(미터)를 반환합니다.
        """
        return sum(
            ((self.G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0) or 0)
            for i in range(len(nodes) - 1)
        )  # 인접 노드 쌍의 length 합산

    def circular_random_walk(self, start_node: int, target_km: float = 3.0) -> list[int]:
        """
        custom_score 기반 확률적 랜덤 워크로 순환 경로 노드 목록을 반환합니다.
        """
        target_m   = target_km * 1000  # 목표 거리(미터)
        path_nodes = [start_node]
        total_dist = 0.0
        current    = start_node
        visited: dict = {}             # 엣지별 방문 횟수
        sx = self.G.nodes[start_node].get("lon", 0)  # 출발점 경도
        sy = self.G.nodes[start_node].get("lat", 0)  # 출발점 위도

        while total_dist < target_m * 0.75:  # 목표의 75%까지 탐색
            neighbors = list(self.G.neighbors(current))
            if not neighbors:
                break

            probs = []
            for n in neighbors:
                ek         = tuple(sorted([current, n]))               # 무방향 엣지 키
                visit_pen  = 1.0 / (1 + visited.get(ek, 0) * 7)        # 재방문 페널티
                degree_pen = 1.0 / (1 + max(0, 3 - self.G.degree(n)))  # 막힌 노드 억제
                score      = (self.G.get_edge_data(current, n) or {}).get("custom_score", 1.0)

                if total_dist / target_m < 0.7:
                    # 전반부에는 출발점에서 멀어지는 방향을 선호
                    dx    = self.G.nodes[n].get("lon", 0) - sx
                    dy    = self.G.nodes[n].get("lat", 0) - sy
                    dist  = (dx ** 2 + dy ** 2) ** 0.5   # 출발점 기준 거리
                    score = score / ((dist + 1e-6) ** 2) # 가까울수록 불리하게 보정

                probs.append((1.0 / (score + 1e-6)) * visit_pen * degree_pen)

            total_p = sum(probs)
            if total_p == 0:
                break

            next_node   = random.choices(neighbors, weights=[p / total_p for p in probs], k=1)[0]
            ek          = tuple(sorted([current, next_node]))
            visited[ek] = visited.get(ek, 0) + 1                                          # 방문 횟수 누적
            total_dist += (self.G.get_edge_data(current, next_node) or {}).get("length", 0)
            path_nodes.append(next_node)
            current = next_node

        if path_nodes[-1] != start_node:  # 출발 노드 미복귀 시 최단 경로로 복귀
            try:
                def _return_w(u, v, d):
                    ek = tuple(sorted([u, v]))
                    return d.get("length", 1.0) * (1 + visited.get(ek, 0) * 10)  # 기방문 엣지 패널티

                return_path = nx.shortest_path(self.G, path_nodes[-1], start_node, weight=_return_w)
                path_nodes += return_path[1:]  # 복귀 경로 연결 (중복 노드 제거)
            except nx.NetworkXNoPath:
                pass

        return path_nodes

    def oneway_waypoint_path(self, start: int, end: int, target_km: float = 3.0) -> list[int]:
        """
        경유 노드를 활용한 우회 편도 경로 노드 목록을 반환합니다.
        """
        target_m = target_km * 1000  # 목표 거리(미터)
        p1       = self.G.nodes[start]
        p2       = self.G.nodes[end]

        candidates = []
        for node, data in self.G.nodes(data=True):
            if node in (start, end):
                continue
            d1    = math.sqrt((data.get("lon", 0) - p1.get("lon", 0)) ** 2 + (data.get("lat", 0) - p1.get("lat", 0)) ** 2) * 111000  # 출발점까지 거리
            d2    = math.sqrt((data.get("lon", 0) - p2.get("lon", 0)) ** 2 + (data.get("lat", 0) - p2.get("lat", 0)) ** 2) * 111000  # 도착점까지 거리
            total = d1 + d2  # 경유 시 총 이동 거리 추정
            if target_m * 0.6 <= total <= target_m * 0.9:  # 목표 거리 60~90% 구간 후보
                candidates.append((node, abs(total - target_m * 0.8)))  # 목표 80%에 가까울수록 우선

        if not candidates:
            # 후보가 없으면 중간점 근처 노드를 경유지로 사용
            mid_lat  = (p1.get("lat", 0) + p2.get("lat", 0)) / 2 + 0.005
            mid_lon  = (p1.get("lon", 0) + p2.get("lon", 0)) / 2 + 0.005
            waypoint = self.find_nearest_node(mid_lat, mid_lon)
        else:
            candidates.sort(key=lambda x: x[1])
            waypoint = random.choice(candidates[:5])[0]  # 상위 5개 중 랜덤 선택

        try:
            path1 = nx.shortest_path(self.G, start, waypoint, weight="custom_score")  # 출발→경유 구간

            saved = {}
            for i in range(len(path1) - 1):
                u, v = path1[i], path1[i + 1]
                if self.G.has_edge(u, v):
                    saved[(u, v)]                = self.G[u][v]["custom_score"]   # 원본 가중치 백업
                    self.G[u][v]["custom_score"] *= 100                           # 1구간 재사용 억제

            try:
                path2 = nx.shortest_path(self.G, waypoint, end, weight="custom_score")  # 경유→도착 구간
            finally:
                for (u, v), w in saved.items():
                    self.G[u][v]["custom_score"] = w  # 가중치 원복

            return path1[:-1] + path2  # 경유 노드 중복 제거 후 연결

        except Exception:
            try:
                return nx.shortest_path(self.G, start, end, weight="custom_score")  # 경유 실패 시 직선 최단 경로
            except Exception:
                return []
