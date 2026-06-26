import math
import random

import networkx as nx

_R1_M: float = 30.0   # ROUT-NODE 1차 탐색 반경 (m)
_R2_M: float = 300.0  # ROUT-NODE 2차 탐색 반경 (m)


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
