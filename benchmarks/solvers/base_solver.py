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
                "paths": list,   # 생성된 경로 목록 (필수)
                "cost": float,   # 알고리즘 자기 기준 비용 (필수) — solver마다 정의가
                                 #   다르므로(거리 m / 누적 custom_score) 알고리즘 간
                                 #   비교에는 쓰지 말 것
                # 이하 전부 선택 필드. 보고하지 않으면 CSV에 None으로 남는다.
                # 전체 목록과 타입은 benchmarks/results.py의 _OPTIONAL_*_KEYS 참고.
                "overlap_ratio": float,  # 베이스 최단경로와 겹치는 거리 비율(편도 전용).
                                         #   순환 solver는 이 값을 계산하지 않으므로
                                         #   보고하지 않는다 — 0.0을 넣으면 "겹침 0%"라는
                                         #   실측값처럼 보인다(2026-09-10 기본값 None으로 변경).
            }
        """
        raise NotImplementedError
