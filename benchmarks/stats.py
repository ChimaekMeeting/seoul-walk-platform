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
import random


def percentile(values, fraction):
    """정렬된 측정값에서 nearest-rank 분위수를 구한다.

    주의: 표본이 작으면 극단 분위수가 최댓값과 같아진다 — n=10에서 p95는
    sorted[ceil(10*0.95)-1] = sorted[9], 즉 최댓값 그 자체다. 조건당 시드 10개 수준에서는
    p95가 worst와 구분되지 않으므로, 조건 단위가 아니라 조건 전체를 모은 뒤 산출할 것.
    """
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)]


# 이 크기까지는 부호 조합을 전수로 돈다(2^18 = 262,144). 그 위는 무작위 재표집.
_EXACT_PERMUTATION_MAX_N = 18
_PERMUTATION_SAMPLES = 20000
_PERMUTATION_SEED = 2026


def paired_permutation_test(differences, samples=_PERMUTATION_SAMPLES, seed=_PERMUTATION_SEED):
    """짝지은 두 알고리즘의 차이가 우연인지 검정한다(양측 p-value).

    왜 이 검정인가:
        같은 조건(출발지·거리)에서 두 알고리즘을 돌린 결과라 표본이 짝지어져 있다.
        짝지은 구조를 쓰면 조건 난이도 차이가 상쇄되므로, 조건을 뭉갠 평균 비교보다
        훨씬 강한 근거가 된다. 귀무가설은 "각 조건에서 차이의 부호가 동전 던지기"이고,
        실제로 부호를 뒤집어가며 관측된 평균차가 얼마나 극단적인지를 센다.

        scipy가 없어도 되는 것이 이 방법의 장점이다 — 정규성 가정도 필요 없다.
        조건이 18개 이하면 2^n개 부호 조합을 전수로 돌아 근사 없는 정확한 p-value가
        나온다(조건 10개면 1,024가지).

    인자:
        differences: 조건마다의 (A 지표 − B 지표). 길이가 곧 조건 수다.

    반환:
        (p_value, n, mean_difference). 표본이 2개 미만이거나 차이가 전부 0이면
        p_value는 None — 검정할 것이 없다.

    ⚠ 이 p-value는 "차이가 0이 아니다"만 말한다. 차이의 크기가 실무적으로 의미 있는지는
      별개이며, 평균차(mean_difference)를 반드시 함께 읽어야 한다.
    """
    values = [float(d) for d in differences if d is not None and not _is_nan(d)]
    n = len(values)
    if n < 2 or all(v == 0.0 for v in values):
        return None, n, (sum(values) / n if n else None)

    observed = sum(values) / n
    target = abs(observed)

    if n <= _EXACT_PERMUTATION_MAX_N:
        extreme = 0
        total = 1 << n
        for mask in range(total):
            flipped = sum(-v if (mask >> i) & 1 else v for i, v in enumerate(values))
            if abs(flipped / n) >= target - _TOLERANCE:
                extreme += 1
        return extreme / total, n, observed

    rng = random.Random(seed)
    extreme = 0
    for _ in range(samples):
        flipped = sum(v if rng.random() < 0.5 else -v for v in values)
        if abs(flipped / n) >= target - _TOLERANCE:
            extreme += 1
    # +1 보정: 관측값 자체를 재표집 분포에 포함시켜 p=0이 나오지 않게 한다
    # (Phipson & Smyth 2010, "Permutation P-values should never be zero").
    return (extreme + 1) / (samples + 1), n, observed


_TOLERANCE = 1e-12


def _is_nan(value) -> bool:
    return value != value
