"""
benchmarks/solvers/base_solver.py

순환 길찾기 알고리즘 벤치마크용 공통 인터페이스 (Strategy Pattern).
개별 알고리즘(RCSP, GRASP, Beam, ALNS 등)은 이 클래스를 상속받아
solve()만 구현하면 benchmark.py 실행기에 그대로 연결된다.
"""

from abc import ABC, abstractmethod
from typing import Any


class BasePathSolver(ABC):
    def __init__(self, name: str):
        self.name = name
        

    @abstractmethod
    def solve(
        self,
        graph: Any,
        start_node: Any,
        target_node: Any,
        params: dict,
    ) -> dict:
        """
        경로 탐색 알고리즘을 실행한다.

        Returns:
            {
                "paths": list,           # 생성된 경로 목록
                "cost": float,           # 총 경로 거리/비용
                "overlap_ratio": float,  # 경로 중복도 (기본값 0.0)
            }
        """
        raise NotImplementedError
