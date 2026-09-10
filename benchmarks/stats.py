"""
benchmarks/stats.py

측정값 요약에 쓰는 순수 통계 헬퍼. 의존성이 없어야 하는 자리다.

percentile()은 원래 benchmarks/runner/waypoint_overlap_audit.py에 있었는데, 그 모듈은
최상단에서 GraphArtifactRepository·PathUtils 등 엔진/저장소 계층을 끌어온다. CSV만 읽는
집계 스크립트가 2줄짜리 분위수 함수 하나 때문에 DB 계층에 의존하게 되므로 여기로 옮겼다
(2026-09-10). 구현을 새로 쓴 것이 아니라 이동한 것이며, waypoint_overlap_audit.py도
이 모듈에서 import해 쓰므로 nearest-rank 정의는 한 벌로 유지된다.
"""

import math


def percentile(values, fraction):
    """정렬된 측정값에서 nearest-rank 분위수를 구한다.

    주의: 표본이 작으면 극단 분위수가 최댓값과 같아진다 — n=10에서 p95는
    sorted[ceil(10*0.95)-1] = sorted[9], 즉 최댓값 그 자체다. 조건당 시드 10개 수준에서는
    p95가 worst와 구분되지 않으므로, 조건 단위가 아니라 조건 전체를 모은 뒤 산출할 것.
    """
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]
