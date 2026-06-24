import networkx as nx

from src.route_engine.engines.path_utils import PathUtils
from src.route_engine.profiles import get_profile
from src.interfaces.schema.walk_schema import CircularMode, WalkRouteStatus, WalkRouteResponse
from src.schema.route_schema import CircularRouteInput


FLAT_THRESHOLD = 0.7  # 평지 판정 경사 점수 기준


class CircularFlatEngine:
    def __init__(self, inp: CircularRouteInput, G: nx.Graph, mode: CircularMode = CircularMode.FLAT):
        self._inp          = inp
        self._G            = G.copy()  # 원본 그래프 보호
        self._utils        = PathUtils(self._G)
        self.mode          = mode
        profile            = get_profile("flat")
        self._weights      = profile.weights
        self._blocked_tags = profile.blocked_tags

    def run(self) -> WalkRouteResponse:
        """
        평지(slope_score 높은 엣지)를 선호하는 순환 경로를 생성합니다.
        """
        start = self._utils.find_nearest_node(self._inp.start_lat, self._inp.start_lon)
        if start is None:
            return WalkRouteResponse(status=WalkRouteStatus.NO_NEAREST_START_NODE, mode=self.mode,
                               coordinates=[], total_km=0.0)

        entry = self._find_flat_entry(start)
        self.flat_entry_node = entry

        path_nodes, total_dist = self._approach(start, entry)
        path_nodes, total_dist = self._loop(path_nodes, total_dist, entry, start)
        path_nodes, total_dist = self._return_phase(path_nodes, total_dist, start)

        if not path_nodes:
            return WalkRouteResponse(status=WalkRouteStatus.NO_PATH, mode=self.mode,
                               coordinates=[], total_km=0.0)

        pruned               = self._utils.prune_dead_ends(path_nodes)
        self.avg_slope_score = self._calc_avg_slope(pruned)
        coords               = self._utils.extract_coordinates(pruned)
        return WalkRouteResponse(
            status      = WalkRouteStatus.SUCCESS if coords else WalkRouteStatus.NO_PATH,
            mode        = self.mode,
            coordinates = coords,
            total_km    = round(total_m / 1000, 2),
        )

    def _find_flat_entry(self, start: int) -> int:
        """
        출발 노드에서 가장 가까운 평지 진입 노드를 반환합니다.
        """
        target_m   = (self._inp.target_km or 3.0) * 1000
        flat_nodes = {
            n
            for u, v, d in self._G.edges(data=True)
            if (d.get("slope_score") or 0) >= FLAT_THRESHOLD
            for n in (u, v)
        }

        if start in flat_nodes or not flat_nodes:
            return start

        sx = self._G.nodes[start].get("lon", 0)
        sy = self._G.nodes[start].get("lat", 0)

        best, best_d = start, float("inf")
        for node in flat_nodes:
            nd = self._G.nodes[node]
            if "lon" not in nd or "lat" not in nd:
                continue
            d = math.sqrt((nd["lon"] - sx) ** 2 + (nd["lat"] - sy) ** 2) * 111000
            if d < best_d and d < target_m * 2:
                best, best_d = node, d
        return best

    def _approach(self, start: int, entry: int) -> tuple[list[int], float]:
        """
        출발 노드에서 평지 진입 노드까지의 접근 경로를 반환합니다.
        """
        if entry == start:
            return [start], 0.0

        try:
            path = nx.shortest_path(self._G, start, entry, weight="length")
        except nx.NetworkXNoPath:
            return [start], 0.0

        dist = sum(
            (self._G.get_edge_data(path[i], path[i + 1]) or {}).get("length", 0)
            for i in range(len(path) - 1)
        )
        return path, dist

    def _loop(
        self, path_nodes: list[int], total_dist: float, entry: int, start: int
    ) -> tuple[list[int], float]:
        """
        평지 구간을 방향 유지하며 순환합니다.
        """
        target_m     = (self._inp.target_km or 3.0) * 1000
        loop_target  = max(target_m - total_dist * 2, target_m * 0.5)
        current      = entry
        visited: dict = {}
        loop_dist    = 0.0
        heading      = random.uniform(0, 360)  # 초기 진행 방향 (랜덤)

        while loop_dist < loop_target:
            neighbors = list(self._G.neighbors(current))
            if not neighbors:
                break

            probs = []
            for n in neighbors:
                ek         = tuple(sorted([current, n]))
                edge_data  = self._G.get_edge_data(current, n) or {}
                slope      = edge_data.get("slope_score", 0.5) or 0.5
                slope_w    = slope if slope >= FLAT_THRESHOLD else 0.01
                ang        = self._angle_to(current, n)
                dir_score  = max(0.01, 1.0 - self._angle_diff(ang, heading) / 180.0)
                visit_pen  = 1.0 / (1 + visited.get(ek, 0) * 6)
                probs.append(slope_w * dir_score * visit_pen)

            total_p = sum(probs)
            if total_p == 0:
                break

            next_node  = random.choices(neighbors, weights=[p / total_p for p in probs], k=1)[0]
            ek         = tuple(sorted([current, next_node]))
            visited[ek] = visited.get(ek, 0) + 1

            step        = (self._G.get_edge_data(current, next_node) or {}).get("length", 0)
            loop_dist  += step
            total_dist += step
            path_nodes.append(next_node)
            current = next_node

            # 진행 방향 갱신 (90도 우회전 유도)
            # 단순 가중 평균은 0°/360° 경계에서 오류 발생 (예: 350°+10° → 299°)
            # atan2 기반 원형 평균으로 단위벡터 합산 후 각도 복원
            cur_ang = self._angle_to(entry, current)
            target  = math.radians((cur_ang + 90) % 360)
            h_rad   = math.radians(heading)
            x = 0.85 * math.cos(h_rad) + 0.15 * math.cos(target)
            y = 0.85 * math.sin(h_rad) + 0.15 * math.sin(target)
            heading = math.degrees(math.atan2(y, x)) % 360

        return path_nodes, total_dist

    def _return_phase(
        self, path_nodes: list[int], total_dist: float, start: int
    ) -> tuple[list[int], float]:
        """
        현재 위치에서 출발 노드로 복귀하는 경로를 연결합니다.
        """
        if path_nodes[-1] == start:
            return path_nodes, total_dist

        try:
            visited_counts = {}
            for i in range(len(path_nodes) - 1):
                ek = tuple(sorted([path_nodes[i], path_nodes[i + 1]]))
                visited_counts[ek] = visited_counts.get(ek, 0) + 1

            def _return_w(u, v, d):
                ek = tuple(sorted([u, v]))
                length = d.get("length", 1.0) or 1.0
                slope  = d.get("slope_score", 0.5) or 0.5
                return length * (2.0 - slope) ** 2 * (1 + visited_counts.get(ek, 0) * 2)

            return_path = nx.shortest_path(self._G, path_nodes[-1], start, weight=_return_w)
            for n in return_path[1:]:
                total_dist += (self._G.get_edge_data(path_nodes[-1], n) or {}).get("length", 0)
                path_nodes.append(n)
        except nx.NetworkXNoPath:
            pass

        return path_nodes, total_dist

    def _angle_to(self, a: int, b: int) -> float:
        """
        노드 a에서 노드 b 방향의 각도(도)를 반환합니다.
        """
        dx = self._G.nodes[b].get("lon", 0) - self._G.nodes[a].get("lon", 0)
        dy = self._G.nodes[b].get("lat", 0) - self._G.nodes[a].get("lat", 0)
        return math.degrees(math.atan2(dx, dy)) % 360

    def _angle_diff(self, a: float, b: float) -> float:
        """
        두 방향각의 최소 차이(도)를 반환합니다.
        """
        d = abs(a - b) % 360
        return d if d <= 180 else 360 - d

    def _calc_avg_slope(self, nodes: list[int]) -> float:
        """
        경로의 평균 경사 점수를 반환합니다.
        """
        scores = [
            (self._G.get_edge_data(nodes[i], nodes[i + 1]) or {}).get("slope_score", 0.5) or 0.5
            for i in range(len(nodes) - 1)
        ]
        return round(sum(scores) / len(scores), 4) if scores else 0.0


