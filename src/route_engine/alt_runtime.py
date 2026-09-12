"""ALT 휴리스틱의 런타임 준비와 그래프 부착.

서버 기동 때 랜드마크를 고르고 거리표를 만들어, `nx.astar_path(heuristic=...)`에 바로
넘길 수 있는 클로저를 그래프에 붙여 둔다. 거리표는 파일로 저장하지 않고 그래프 로드
직후 메모리에 1회만 만든다(2026-09-12 결정).

지원하는 선택법은 Planar와 Random 둘뿐이다. Farthest·Avoid는 전처리 비용 대비 이득이
확인되지 않아 지원 목록에서 뺐다 — 어떤 선택법을 서비스에 쓸 수 있는지는 이 모듈의
`prepare_alt_heuristic()` 하나가 결정한다(선정 근거는
`analysis/route_engine/alt_landmark_selection_validation.md`).

**실패해도 서버 기동을 막지 않는다.** 랜드마크 선정이나 거리표 생성이 어떤 이유로든
실패하면 warning 로그를 남기고 `(None, None)`을 돌려주며, 엔진은 기존 Haversine
휴리스틱으로 그대로 동작한다. ALT는 탐색을 빠르게 할 뿐 결과 경로를 바꾸지 않으므로
(둘 다 admissible) 폴백해도 응답 계약이 달라지지 않는다.

## 순환 import

`landmark_*` 모듈은 함수 안에서 지연 import한다. 이 모듈들이 `PathUtils`를 쓰려고
`src.route_engine.engines.path_utils`를 가져오는데, 그러면 `engines/__init__.py`가 실행
되면서 모든 엔진(= `oneway_astar` 포함)을 import하고, 그 `oneway_astar`가 다시 이 모듈을
import해 순환이 닫힌다. 최상단 import를 그대로 두면 `ImportError: cannot import name
'get_alt_heuristic' from partially initialized module`이 난다.

지연 import 비용은 문제가 되지 않는다 — `prepare_alt_heuristic()`은 기동 때 1회만
호출되고, 엔진이 매 요청 호출하는 `get_alt_heuristic()`에는 import가 없다.

## 거리표를 G.graph에 직접 넣지 않는 이유 (2026-09-12 확인)

거리표(k=8 기준 약 16MB, 128만 항목)는 클로저 안에만 두고 `G.graph`에는 **호출 가능한
함수 객체만** 올린다. `visualizations/route_experiment.py`가 실행마다
`copy.deepcopy(graph)`를 하는데, `copy.deepcopy`는 함수 객체를 원자값으로 취급해 그대로
돌려주므로(확인: 복사본과 원본의 함수가 같은 객체, 클로저가 잡은 표도 같은 객체) 표가
복제되지 않는다. 반대로 `G.graph["alt_table"] = {...}`처럼 dict를 직접 올리면 deepcopy가
표 전체를 복제한다.

부착 위치로 `G.graph`를 고른 근거:
- `GraphArtifactRepository._validate_graph`는 노드·엣지 속성만 보고 `graph.graph`는 보지
  않는다. 부착은 `load()` 이후에 하므로 검증 경로와 겹치지도 않는다.
- `precompute_scoring_features`가 이미 `graph.graph`에 feature cache를 올리고 있어 같은
  자리를 쓰는 선례가 있다.
- `copy.deepcopy(G)`가 예외 없이 동작한다(위 참고).

⚠ 다만 **이 키가 붙은 그래프는 pickle되지 않는다**(로컬 클로저는 pickle 불가). 그래프를
pickle하는 곳은 `GraphArtifactRepository.save()` 하나뿐이고, 호출자는
`scripts/build_walk_graph.py`(PostgreSQL에서 새로 만든 그래프를 저장)와
`tests/unit/test_graph_artifact_repository.py`(테스트가 직접 만든 그래프) 둘뿐이라
런타임 그래프가 그 경로로 가지 않는다. 런타임 그래프를 pickle해야 하는 코드가 생기면
이 제약을 먼저 확인할 것.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from time import perf_counter

import networkx as nx

logger = logging.getLogger(__name__)

HEURISTIC_KEY = "alt_heuristic"
INFO_KEY = "alt_info"

# 서비스에 연결할 수 있는 선택법. Farthest·Avoid는 의도적으로 빠져 있다.
SUPPORTED_METHODS = ("planar", "random")


@dataclass(frozen=True)
class AltRuntimeInfo:
    """이번 기동에서 준비한 ALT 휴리스틱의 내역. 로그·문서·테스트가 함께 쓴다."""

    method: str
    k_requested: int
    k_actual: int
    landmarks: list[int] = field(default_factory=list)
    select_s: float = 0.0
    table_s: float = 0.0
    table_entries: int = 0


def _select_landmarks(G: nx.Graph, method: str, k: int, seed: int) -> list[int]:
    """지원 선택법만 호출한다. Planar의 k는 섹터 수(n_sectors) 의미다.

    landmark_* 모듈은 여기서 지연 import한다 — 모듈 최상단에서 가져오면 순환 import가
    된다(자세한 내용은 모듈 docstring "순환 import" 참고).
    """
    from src.route_engine.landmark_planar import select_landmarks_planar
    from src.route_engine.landmark_random import select_landmarks_random

    if method == "planar":
        return select_landmarks_planar(G, k)
    return select_landmarks_random(G, k, seed=seed)


def prepare_alt_heuristic(
    G: nx.Graph,
    *,
    enabled: bool,
    method: str,
    k: int,
    seed: int,
    weight: str = "length",
) -> tuple[Callable[[int, int], float] | None, AltRuntimeInfo | None]:
    """랜드마크를 고르고 거리표를 만들어 A* 휴리스틱 클로저를 돌려준다.

    Args:
        enabled: False면 아무것도 하지 않고 `(None, None)`을 돌려준다.
        method: `SUPPORTED_METHODS` 중 하나.
        k: 랜드마크 개수(Planar는 섹터 수라 실제 반환 개수가 더 적을 수 있다).
        seed: Random 선택법에만 쓰인다. Planar는 좌표 결정론이라 무시한다.
        weight: 거리표와 랜드마크 선정에 쓸 엣지 weight. 실제 탐색과 같아야
            삼각부등식 하한이 탐색 비용의 하한이 되어 admissible하다.

    Returns:
        `(heuristic, info)`. 준비하지 못했으면 `(None, None)` — 호출자는 기존 Haversine
        휴리스틱으로 폴백하면 된다.

    Raises:
        ValueError: `method`가 지원 목록에 없을 때. 이것만 예외로 올린다(설정 오타 등
            프로그래밍 오류라 조용히 넘기면 안 된다). 선정·거리표 생성 중에 생기는
            런타임 오류는 전부 잡아서 `(None, None)`으로 바꾼다.
    """
    if not enabled:
        logger.info("ALT 휴리스틱이 꺼져 있습니다(WALK_ALT_ENABLED=false). Haversine을 씁니다.")
        return None, None

    if method not in SUPPORTED_METHODS:
        raise ValueError(
            f"지원하지 않는 ALT 선택법입니다: {method!r}. "
            f"사용 가능: {', '.join(SUPPORTED_METHODS)}"
        )

    try:
        t0 = perf_counter()
        landmarks = _select_landmarks(G, method, k, seed)
        select_s = perf_counter() - t0

        if not landmarks:
            logger.warning(
                "ALT 랜드마크를 하나도 고르지 못했습니다(method=%s, k=%s). Haversine으로 "
                "폴백합니다.",
                method,
                k,
            )
            return None, None

        from src.route_engine.landmark_shared import build_alt_heuristic

        t0 = perf_counter()
        heuristic, table = build_alt_heuristic(G, landmarks, weight=weight)
        table_s = perf_counter() - t0
    except Exception as exc:  # 기동을 막지 않는다 — 어떤 실패든 Haversine으로 돌아간다.
        logger.warning(
            "ALT 휴리스틱 준비에 실패해 Haversine으로 폴백합니다(method=%s, k=%s): %s: %s",
            method,
            k,
            type(exc).__name__,
            exc,
        )
        return None, None

    info = AltRuntimeInfo(
        method=method,
        k_requested=k,
        k_actual=len(landmarks),
        landmarks=[int(n) for n in landmarks],
        select_s=select_s,
        table_s=table_s,
        table_entries=sum(len(row) for row in table.values()),
    )
    logger.info(
        "ALT 휴리스틱 준비 완료: method=%s k_requested=%d k_actual=%d "
        "선정 %.2fs 거리표 %.2fs 항목 %d개",
        info.method,
        info.k_requested,
        info.k_actual,
        info.select_s,
        info.table_s,
        info.table_entries,
    )
    return heuristic, info


def attach_alt_heuristic(
    G: nx.Graph,
    heuristic: Callable[[int, int], float] | None,
    info: AltRuntimeInfo | None,
) -> None:
    """준비한 휴리스틱을 그래프에 붙인다.

    `heuristic`이 None이면(준비 실패·비활성) 이전에 붙어 있던 값을 지운다 — 같은
    프로세스에서 다시 초기화할 때 낡은 휴리스틱이 남지 않도록.
    """
    if heuristic is None:
        G.graph.pop(HEURISTIC_KEY, None)
        G.graph.pop(INFO_KEY, None)
        return
    G.graph[HEURISTIC_KEY] = heuristic
    G.graph[INFO_KEY] = asdict(info) if info is not None else None


def get_alt_heuristic(G: nx.Graph) -> Callable[[int, int], float] | None:
    """그래프에 붙은 ALT 휴리스틱. 없으면 None(호출자는 Haversine으로 폴백)."""
    return G.graph.get(HEURISTIC_KEY)


def get_alt_info(G: nx.Graph) -> dict | None:
    """그래프에 붙은 ALT 준비 내역(dict). 없으면 None."""
    return G.graph.get(INFO_KEY)
