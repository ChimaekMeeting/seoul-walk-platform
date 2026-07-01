from pathlib import Path

# 경로
BENCH_DIR = Path(__file__).resolve().parent
DATASETS_DIR = BENCH_DIR / "datasets"
FIXTURES_DIR = BENCH_DIR / "fixtures"
RESULTS_DIR  = BENCH_DIR / "results"

# 기본 입력 파일
ROUTE_NODES_PARQUET  = FIXTURES_DIR / "route_nodes.parquet"  # 도보 그래프 노드
ROUTE_EDGES_PARQUET  = FIXTURES_DIR / "route_edges.parquet"  # 도보 그래프 엣지
ROUTE_ENGINE_DATASET = DATASETS_DIR / "route_engine.json"    # 테스트 데이터셋

# 경로 엔진 알고리즘 성능 테스트 시 필요한 상수
LENGTH_TOLERANCE = 0.10  # ±10% 오차 범위
LATENCY_REPEAT   = 5     # latency 측정 시, 반복 횟수