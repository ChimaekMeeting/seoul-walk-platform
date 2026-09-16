# [버그] beam-circular 벤치마크 solver가 항상 TypeError로 실패함

## 요약

`benchmarks/solvers/_circular_engine_common.py::run_circular_engine()`이
`CircularBeamEngine.find_path()`의 반환 타입을 잘못 처리해서, 공식 벤치마크
스위트(`benchmarks/benchmark.py`, `benchmarks/run_all_scenarios.py`)로
`beam-circular`를 실행하면 항상 실패한다.

## 재현 방법

```python
from benchmarks.benchmark import _load_default_graph, SOLVER_REGISTRY
from src.route_engine.scoring.scoring_engine import precompute_scoring_features
from src.route_engine.engines.path_utils import PathUtils

g = _load_default_graph()
precompute_scoring_features(g)
utils = PathUtils(g)
start_node = utils.find_nearest_node(37.451699, 126.911126)

solver = SOLVER_REGISTRY["beam-circular"]
solver.solve(g, start_node, start_node, {"target_km": 4.5, "profile": "default"})
# TypeError: unhashable type: 'list'
```

## 원인

```
CircularBeamEngine.find_path()
    반환: list[list[int]]   (다양화된 후보 경로 여러 개, 최대 3개)

run_circular_engine()
    기대: list[int]          (단일 경로)

prune_dead_ends()
    단일 경로(list[int])를 기대하지만 후보 리스트(list[list[int]])를 그대로 받음
    → node_positions 딕셔너리 키로 list를 쓰려다 TypeError
```

`circular_beam.py`의 `run()` 메서드는 `for nodes in candidates: ...`로 후보마다
순회하며 정상 처리하지만(38~97행), `benchmarks/solvers/_circular_engine_common.py`의
`run_circular_engine()`은 `candidates` 전체를 그대로 `prune_dead_ends()`에 넘긴다.

다른 circular 엔진(`circular_grasp.py`, `circular_alns.py`, `circular_rcsp.py`,
`circular_grasp_waypoint_*.py`)은 `find_path()`가 `list[int]`(단일 경로)를 반환하므로
이 버그가 없다 — `circular_beam.py`만 해당.

## 영향 범위

- `benchmarks/solvers/beam_solver.py::CircularBeamSolver.solve()`
- 이를 사용하는 `benchmarks/benchmark.py`, `benchmarks/run_all_scenarios.py`의
  `beam-circular` 알고리즘 전체

## 수정 방향 (택 1, 논의 필요)

**A. 대표 후보 하나만 사용**
```python
candidate_paths = engine.find_path(start_node, target_km)
nodes = candidate_paths[0] if candidate_paths else None
```
이 경우 "왜 0번째 후보가 대표인지"(예: `find_path` 내부에서 이미 거리 적합도
기준으로 정렬돼 있는지)를 확인하고 docstring에 명시해야 한다.

**B. 후보 전체를 처리**
```python
pruned_paths = [prune_dead_ends(p) for p in candidate_paths]
```
이 경우 `run_circular_engine()`의 반환 타입이 바뀌므로, 이를 소비하는
벤치마크 결과 저장·집계 코드(`benchmark.py`의 `RESULT_COLUMNS` 등)까지
함께 검토해야 한다.

## 참고

- `analysis/turn_cost/turn_cost_distribution_check.py`에서 이 버그를 우회해
  (A) 방식으로 임시 처리한 뒤 `turn_cost` 분포를 분석했다 — 그 결과의
  `beam-circular` 값은 공식 벤치마크 경로로 재현된 값이 아니라는 점에 주의.
- 이번 turn_cost 작업(`feature/turn-cost-metric` 브랜치)과는 무관한 기존 버그이므로
  별도 브랜치/커밋으로 수정할 것을 권장.
