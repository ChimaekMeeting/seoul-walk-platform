import math

import networkx as nx


class PathUtils:
    @staticmethod
    def find_nearest_node(G: nx.Graph, lat: float, lon: float) -> int:
        """
        위경도와 가장 가까운 그래프 노드 ID를 반환합니다.
        """
        min_dist = float("inf")
        nearest = None

        # 전체 노드 순회하며 유클리드 거리 비교
        for node_id, data in G.nodes(data=True):
            node_lat = data.get("y")
            node_lon = data.get("x")
            if node_lat is None or node_lon is None:
                continue
            dist = math.sqrt((lat - node_lat) ** 2 + (lon - node_lon) ** 2)
            if dist < min_dist:
                min_dist = dist
                nearest = node_id

        return nearest

    @staticmethod
    def extract_coordinates(G: nx.Graph, node_list: list) -> list:
        """
        노드 ID 목록을 [[위도, 경도], ...] 형태의 좌표 목록으로 변환합니다.
        """
        # 그래프에 존재하는 노드만 추출
        return [
            [G.nodes[n]["y"], G.nodes[n]["x"]]
            for n in node_list
            if n in G.nodes
        ]

    @staticmethod
    def prune_dead_ends(path_nodes: list, G: nx.Graph, max_branch_length: float = 400.0) -> list:
        """
        경로 내 짧은 왕복 구간(dead-end)을 반복 제거한 노드 목록을 반환합니다.
        """
        pruned = list(path_nodes)
        changed = True

        while changed:
            changed = False
            node_positions = {}
            candidates = []

            # 동일 노드가 두 번 등장하는 구간 탐색
            for i, node in enumerate(pruned):
                if node in node_positions:
                    first = node_positions[node]

                    # 구간 길이 계산
                    branch_length = sum(
                        (G.get_edge_data(pruned[j], pruned[j + 1]) or {}).get("length", 0)
                        for j in range(first, i)
                    )
                    if branch_length < max_branch_length:
                        candidates.append((branch_length, first, i))
                else:
                    node_positions[node] = i

            # 가장 짧은 왕복 구간 제거
            if candidates:
                _, first, last = min(candidates, key=lambda x: x[0])
                pruned = pruned[: first + 1] + pruned[last + 1:]
                changed = True

        return pruned

    @staticmethod
    def remove_dead_ends(G: nx.Graph) -> nx.Graph:
        """
        차수가 1인 막다른 노드를 모두 제거한 그래프를 반환합니다.
        """
        G = G.copy()

        # 막다른 노드가 없을 때까지 반복 제거
        while True:
            dead_ends = [n for n, d in G.degree() if d == 1]
            if not dead_ends:
                break
            G.remove_nodes_from(dead_ends)

        return G

    @staticmethod
    def remove_invalid_nodes(G: nx.Graph) -> nx.Graph:
        """
        x/y 좌표 속성이 없는 노드를 제거한 그래프를 반환합니다.
        """
        # 좌표 누락 노드 수집
        invalid = [n for n, d in G.nodes(data=True) if "x" not in d or "y" not in d]
        if not invalid:
            return G

        # 원본 보존을 위해 복사 후 제거
        G = G.copy()
        G.remove_nodes_from(invalid)
        return G

    @staticmethod
    def path_distance_m(G: nx.Graph, path: list) -> float:
        """
        경로 노드 목록의 총 거리를 미터 단위로 반환합니다.
        """
        # 인접한 노드 쌍의 엣지 길이 합산
        return sum(
            (G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
            for i in range(len(path) - 1)
        )

    @staticmethod
    def subgraph_near(G: nx.Graph, lat: float, lon: float, radius_m: float) -> nx.Graph:
        """
        위경도 기준 반경 내 노드만 포함한 서브그래프를 반환합니다.
        """
        # 위도 1도 ≈ 111km 기준으로 경계 박스 계산
        deg = radius_m / 111000
        nodes = [
            n
            for n, d in G.nodes(data=True)
            if "y" in d
            and "x" in d
            and abs(d["y"] - lat) <= deg
            and abs(d["x"] - lon) <= deg * 1.3
        ]
        return G.subgraph(nodes).copy()

    @staticmethod
    def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """
        두 위경도 좌표 사이의 실제 거리를 미터 단위로 반환합니다.
        """
        R = 6_371_000.0
        phi1, phi2 = math.radians(lat1), math.radians(lat2)

        # Haversine 공식 적용
        a = (
            math.sin((lat2 - lat1) * math.pi / 180 / 2) ** 2
            + math.cos(phi1) * math.cos(phi2)
            * math.sin((lon2 - lon1) * math.pi / 180 / 2) ** 2
        )
        return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def flat_edge_weight(u: int, v: int, data: dict) -> float:
        """
        평지 경로용 엣지 비용을 반환합니다. 경사가 낮을수록 비용이 낮아집니다.
        """
        length = data.get("length", 1.0) or 1.0
        slope  = data.get("slope_score", 0.5) or 0.5

        # cost = length × (2 - slope)² : slope가 높을수록 비용 급증
        return length * (2.0 - slope) ** 2
