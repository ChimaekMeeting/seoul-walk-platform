"""
benchmarks/tests/fixtures.py

벤치마크 하네스(run_benchmark) 테스트용 더미 solver 모음.

multiprocessing(spawn)이 자식 프로세스에서 이 클래스들을 다시 import해야 하므로,
반드시 모듈 최상위(top-level)에 정의한다 — pytest 함수 안의 로컬 클래스는 spawn이
pickle하지 못해 테스트 자체가 깨진다.
"""

import time

from benchmarks.solvers.base_solver import BasePathSolver


class SleepSolver(BasePathSolver):
    """지정한 시간만큼 sleep 후 정상 결과를 반환한다. (시간 측정 정확도 테스트용)"""

    def __init__(self, name: str, sleep_sec: float = 0.0, cost: float = 1234.5, overlap_ratio: float = 0.0):
        super().__init__(name)
        self.sleep_sec = sleep_sec
        self.cost = cost
        self.overlap_ratio = overlap_ratio

    def solve(self, graph, start_node, target_node, params):
        if self.sleep_sec:
            time.sleep(self.sleep_sec)
        return {"paths": [[start_node, target_node]], "cost": self.cost, "overlap_ratio": self.overlap_ratio}


class NoOverlapRatioSolver(BasePathSolver):
    """overlap_ratio를 아예 안 주는 solver. 명세대로 기본값 0.0이 적용되어야 한다."""

    def solve(self, graph, start_node, target_node, params):
        return {"paths": [[start_node, target_node]], "cost": 42.0}


class MissingCostSolver(BasePathSolver):
    """cost 키가 없는(규격 위반) solver."""

    def solve(self, graph, start_node, target_node, params):
        return {"paths": [[start_node, target_node]]}


class MissingPathsSolver(BasePathSolver):
    """paths 키가 없는(규격 위반) solver."""

    def solve(self, graph, start_node, target_node, params):
        return {"cost": 1.0}


class BadPathsTypeSolver(BasePathSolver):
    """paths가 list가 아닌(타입 위반) solver."""

    def solve(self, graph, start_node, target_node, params):
        return {"paths": "not-a-list", "cost": 1.0}


class BadCostTypeSolver(BasePathSolver):
    """cost가 숫자가 아닌(타입 위반) solver."""

    def solve(self, graph, start_node, target_node, params):
        return {"paths": [], "cost": "not-a-number"}


class NonDictReturnSolver(BasePathSolver):
    """dict가 아닌 값을 반환하는 solver."""

    def solve(self, graph, start_node, target_node, params):
        return ["paths", "cost"]


class RaisingSolver(BasePathSolver):
    """solve() 내부에서 예외를 던지는 solver. (경로 미발생 시뮬레이션)"""

    def solve(self, graph, start_node, target_node, params):
        raise RuntimeError("경로를 찾지 못함")


class HangingSolver(BasePathSolver):
    """무한루프에 빠지는 solver. (타임아웃 시뮬레이션)"""

    def solve(self, graph, start_node, target_node, params):
        while True:
            time.sleep(0.05)


class MutatingSolver(BasePathSolver):
    """전달받은 graph를 in-place로 수정하는 solver. (그래프 격리 검증용)"""

    def solve(self, graph, start_node, target_node, params):
        graph["mutated_by"] = self.name
        return {"paths": [[start_node, target_node]], "cost": 1.0, "overlap_ratio": 0.0}


class FixedPathSolver(BasePathSolver):
    """정해진 노드 순서를 그대로 경로로 반환하는 solver.

    실제 탐색은 하지 않고 지정된 경로만 돌려줘서, 하네스의 거리/루프폐합 계산이
    정확한지를 '정답을 알고 있는' 경로로 검증할 때 쓴다.
    """

    def __init__(self, name: str, path: list, cost: float = 0.0, sleep_sec: float = 0.0):
        super().__init__(name)
        self.path = path
        self.cost = cost
        self.sleep_sec = sleep_sec

    def solve(self, graph, start_node, target_node, params):
        if self.sleep_sec:
            time.sleep(self.sleep_sec)
        return {"paths": [self.path], "cost": self.cost, "overlap_ratio": 0.0}


class ParamDrivenPathSolver(BasePathSolver):
    """params['path']에 지정된 경로를 그대로 반환하는 solver.

    solver 내부 상태가 아니라 params로 시나리오를 제어하므로, 여러 번의 run_benchmark
    호출에 걸쳐 완전히 결정론적으로 다른 경로를 재현할 수 있다 (solver는 매번 새
    프로세스에서 언피클되므로, 인스턴스 속성으로 호출 횟수를 세는 방식은 프로세스
    경계 때문에 동작하지 않는다).
    """

    def solve(self, graph, start_node, target_node, params):
        return {"paths": [params["path"]], "cost": 0.0, "overlap_ratio": 0.0}


class CpuLoopSolver(BasePathSolver):
    """sleep이 아니라 실제 CPU 연산(순수 파이썬 루프)을 수행하는 solver.

    작업량(iterations)에 따라 elapsed_sec이 실제로 커지는지 검증하는 성능 테스트용.
    """

    def __init__(self, name: str, iterations: int):
        super().__init__(name)
        self.iterations = iterations

    def solve(self, graph, start_node, target_node, params):
        x = 0
        for i in range(self.iterations):
            x += i * i
        return {"paths": [[start_node, target_node]], "cost": float(x % 1000), "overlap_ratio": 0.0}
