"""
benchmarks/solvers/dummy_solver.py

BasePathSolver 인터페이스가 benchmark.py 실행기와 올바르게 동작하는지
검증하기 위한 더미 구현체. 실제 탐색 없이 가짜 실행 시간과 더미 결과만 반환한다.
"""

import time

from benchmarks.solvers.base_solver import BasePathSolver


class DummySolver(BasePathSolver):
    def __init__(self, name: str = "DummySolver", fake_delay_sec: float = 0.1):
        super().__init__(name)
        self.fake_delay_sec = fake_delay_sec

    def solve(self, graph, start_node, target_node, params) -> dict:
        time.sleep(self.fake_delay_sec)

        dummy_path = [start_node, target_node]
        return {
            "paths": [dummy_path],
            "cost": 1234.5,
            "overlap_ratio": 0.0,
        }
