import math
import random

import networkx as nx

_R1_M: float = 30.0   # ROUT-NODE 1차 탐색 반경 (m)
_R2_M: float = 100.0  # ROUT-NODE 2차 탐색 반경 (m)


class PathUtils:
    def __init__(self, G: nx.Graph):
        self.G = G

    @staticmethod
    def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """두 좌표 사이의 Haversine 거리(미터)를 반환합니다."""
        R  = 6_371_000.0
        p1 = math.radians(lat1)
        p2 = math.radians(lat2)
        dp = math.radians(lat2 - lat1)
        dl = math.radians(lon2 - lon1)
        a  = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    def find_nearest_node(
        self,
        lat: float,
        lon: float,
        max_dist_m: float | None = None,
    ) -> int | None:
        """
        위경도에서 그래프상 가장 가까운 노드 ID를 반환합니다.
        max_dist_m 지정 시 해당 반경(m) 이내 노드만 탐색합니다.
        """
        if self.G.is_directed():
            largest_cc = max(nx.weakly_connected_components(self.G), key=len)
        else:
            largest_cc = max(nx.connected_components(self.G), key=len)
        min_dist = float("inf")
        nearest  = None
        for node_id, data in self.G.nodes(data=True):
            if node_id not in largest_cc:
                continue
            node_lat = data.get("lat")
            node_lon = data.get("lon")
            if node_lat is None or node_lon is None:
                continue
            dist_m = self._haversine_m(lat, lon, node_lat, node_lon)
            if max_dist_m is not None and dist_m > max_dist_m:
                continue
            if dist_m < min_dist:
                min_dist = dist_m
                nearest  = node_id
        return nearest

    def find_nearest_node_with_expansion(
        self,
        lat: float,
        lon: float,
        r1_m: float = _R1_M,
        r2_m: float = _R2_M,
    ) -> int | None:
        """
        ROUT-NODE-001/002: R1 → R2 2단계 반경 확장 탐색.
        R1 이내에 없으면 R2까지 확장하여 재탐색합니다.
        두 단계 모두 실패하면 None을 반환합니다.
        """
        node = self.find_nearest_node(lat, lon, max_dist_m=r1_m)
        if node is None:
            node = self.find_nearest_node(lat, lon, max_dist_m=r2_m)
        return node

    def extract_coordinates(self, node_list: list) -> list:
        """노드 ID 리스트 → [[lat, lon], ...] 변환"""
        result = []
        for n in node_list:
            if n not in self.G.nodes:
                continue
            nd  = self.G.nodes[n]
            lat = nd.get("lat")
            lon = nd.get("lon")
            # 직접 접근(["lat"])은 속성 없는 노드에서 KeyError 발생 → .get()으로 안전 처리
            if lat is not None and lon is not None:
                result.append([lat, lon])
        return result

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
            (self.G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("length", 0)
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
                    # 전반부: 출발점에서 멀수록 score 작아짐 → 확률 높아짐 (탐색 확장)
                    dx    = self.G.nodes[n].get("lon", 0) - sx
                    dy    = self.G.nodes[n].get("lat", 0) - sy
                    dist  = (dx ** 2 + dy ** 2) ** 0.5
                    score = score / ((dist + 1e-6) ** 2)
                else:
                    # 후반부: 출발점에서 멀수록 score 커짐 → 확률 낮아짐 (귀환 유도)
                    # Dijkstra 복귀 전 워커가 자연스럽게 출발점 방향으로 수렴하도록 함
                    dx    = self.G.nodes[n].get("lon", 0) - sx
                    dy    = self.G.nodes[n].get("lat", 0) - sy
                    dist  = (dx ** 2 + dy ** 2) ** 0.5
                    score = score * (1.0 + dist ** 2 * 1e6)

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

        lon1, lat1 = p1.get("lon", 0), p1.get("lat", 0)
        lon2, lat2 = p2.get("lon", 0), p2.get("lat", 0)
        dx, dy     = lon2 - lon1, lat2 - lat1
        dist_se    = math.sqrt(dx ** 2 + dy ** 2)

        # 출발-도착 직선에 수직인 방향으로 중점을 offset하여 실제 우회 루프 유도
        # 기존 방식(직선거리 비율 필터만)은 직선 근처 노드가 선택되어 우회 효과 약함
        offset_deg = (target_km * 0.35) / 111.0
        if dist_se > 1e-9:
            side = random.choice([1, -1])
            px   = -dy / dist_se * side  # 수직 단위벡터 (90도 회전)
            py   =  dx / dist_se * side
        else:
            angle = random.uniform(0, 2 * math.pi)
            px, py = math.cos(angle), math.sin(angle)

        target_lon = (lon1 + lon2) / 2 + px * offset_deg
        target_lat = (lat1 + lat2) / 2 + py * offset_deg

        candidates = []
        for node, data in self.G.nodes(data=True):
            if node in (start, end):
                continue
            nlon, nlat = data.get("lon", 0), data.get("lat", 0)
            d1    = math.sqrt((nlon - lon1) ** 2 + (nlat - lat1) ** 2) * 111000
            d2    = math.sqrt((nlon - lon2) ** 2 + (nlat - lat2) ** 2) * 111000
            total = d1 + d2
            if target_m * 0.6 <= total <= target_m * 0.9:
                d_target = math.sqrt((nlon - target_lon) ** 2 + (nlat - target_lat) ** 2)
                candidates.append((node, d_target))

        if not candidates:
            waypoint = self.find_nearest_node(target_lat, target_lon)
        else:
            candidates.sort(key=lambda x: x[1])
            waypoint = random.choice(candidates[:5])[0]  # 상위 5개 중 랜덤 선택

        try:
            path1       = nx.shortest_path(self.G, start, waypoint, weight="custom_score")
            path1_edges = set(zip(path1[:-1], path1[1:]))

            # G 엣지를 직접 수정하지 않고 클로저로 페널티 적용 → 그래프 오염 방지
            def penalized_weight(u, v, data):
                base = data.get("custom_score", 1.0)
                return base * 100.0 if (u, v) in path1_edges or (v, u) in path1_edges else base

            path2 = nx.shortest_path(self.G, waypoint, end, weight=penalized_weight)
            return path1[:-1] + path2

        except Exception:
            try:
                return nx.shortest_path(self.G, start, end, weight="custom_score")  # 경유 실패 시 직선 최단 경로
            except Exception:
                return []
