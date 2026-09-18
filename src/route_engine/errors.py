"""
src/route_engine/errors.py

route_engine 공용 예외. 저장소 안의 어떤 모듈도 import하지 않는 leaf 모듈이다.

왜 별도 파일인가
----------------
MissingEdgeAttributeError는 원래 waypoint_route_builder.py에 있었는데, 그 모듈은
engines/path_utils를 import하고 그 경로에서 engines/__init__.py가 실행되면서
engines 전체(oneway_astar 포함)가 로드된다. 그래서 scoring 쪽 모듈이 예외만
가져오려 해도 다음 순환이 생겼다.

    scoring.scoring_engine (WeightedEdgeCost가 여기 있음)
      -> waypoint_route_builder
        -> engines.path_utils  (engines/__init__ 실행)
          -> engines.oneway_astar
            -> scoring.scoring_engine   # 부분 초기화 상태

예외를 여기로 옮기고 waypoint_route_builder가 재-export하면 기존 import 경로
(`from src.route_engine.waypoint_route_builder import MissingEdgeAttributeError`,
engines/grasp_waypoint_common의 재-export)는 그대로 유지되면서 순환이 끊긴다.
"""

from __future__ import annotations


class MissingEdgeAttributeError(KeyError):
    """엣지에 필수 속성(예: length)이 없을 때 던진다. 0으로 조용히 대체하지 않는다 —
    그렇게 하면 모든 비용이 0으로 계산되는 오류가 숨겨질 수 있다."""
