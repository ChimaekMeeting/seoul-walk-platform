# 선호 경로의 우회 제한 정책 검토

> 상태: Proposal — 서비스 적용 미합의, 실험 코드만 보존
> 기준일: 2026-09-17
> 관련 코드: `src/route_engine/scoring/detour_cap.py`, `src/route_engine/engines/waypoint.py`

## 논의할 문제

안전·편안 선호를 반영하면 최단 경로보다 길어질 수 있다. 얼마나 긴 경로를 허용할지,
초과하면 사용자 선호를 버려도 되는지는 팀이 정할 서비스 정책이다. **30%는 승인된
기준이 아니며, 초과 시 최단으로 강제 대체하는 방식도 미합의다.**

현재 일반 요청은 이 제한을 적용하지 않는다. 설문/프로필 기본값과 대화 선호를 섞은
가중치는 유지한다. 탐색 자체가 실패해 거리 경로를 반환하는 복구는 별개이며,
`preferred_search_failed`로 선호를 끝까지 적용하지 못했다는 사실을 표시한다.
현재 동작의 단일 기준은 [경로 엔진 계약](../route_engine/README.md)이다.

## 남겨 둔 구현과 재현

- `apply_detour_cap(G, weighted_path, physical_path, max_ratio)`는 두 경로의 반올림 전
  `length` 합을 비교한다. `weighted > physical × (1 + max_ratio)`일 때만 대체한다.
- `WaypointComposerEngine._build_distance_baseline`은 같은 경유지 순서에 대해
  가중치·재방문 페널티 없는 거리 기준 경로를 만든다.
- `_apply_detour_cap`은 전체 경로를 비교하고, 초과 시 좌표와 거리를 기준 경로로 교체한다.
  기준 경로 생성 실패 시 선호 경로를 유지하면서 `baseline_failed`를 표시한다.
- Composer를 직접 생성할 때 `experimental_detour_max_ratio=비율`을 명시하면 이 실험을
  재현할 수 있다. 기본값은 `None`이며 **RouteService/API/운영 환경설정에는 연결하지 않는다.**
  비율에 확정 기본값은 없다. Beam 혼합 요청과 선호 탐색 실패 후 거리 대체에는 적용하지 않는다.
- 실험은 기준 경로를 구하므로 구간당 A* 실행이 추가된다. 일반 요청에는 이 비용이 없다.
  A* 이외 좌표 스냅과 그래프 점수 벡터 계산 비용도 있으므로 전체 요청 성능은 별도 측정해야 한다.

`tests/unit/test_waypoint_detour_cap.py`에 명시적 실험의 경계·대체·기준 경로 실패·경유지
보존 테스트와, 일반 요청이 30%보다 긴 선호 경로도 유지하는 회귀 테스트를 함께 둔다.

### 검증 기록

2026-09-17, Windows 저장소의 `.venv` Python 환경에서 확인했다.

- `python -m pytest tests/unit/test_weighted_cost_runtime.py tests/unit/test_waypoint_detour_cap.py tests/unit/test_oneway_astar_weighted.py tests/unit/test_weighted_edge_cost.py tests/unit/test_graph_repository_scores.py -q`: 262 passed.
- `python -m pytest tests/unit -q`: 변경 전 878 passed / 48 failed, 변경 후 893 passed / 48 failed.
  실패 항목과 실행 단계까지 비교해 새 실패가 없음을 확인했다.
- 가중 비용·상한 함수·A*·Composer·기동 준비 모듈을 각각 새 프로세스에서 단독 import했다.
- DB 조회와 실제 artifact의 점수 활성화는 이번 검증 범위에 포함하지 않았다.

## 팀에서 결정할 사항

1. 우회 제한이 필요한 요청은 무엇인가: 최단 연결, 선호 연결, 목표 거리 산책을 구분한다.
2. 거리 기준은 무엇인가: 같은 경유지 순서의 최단거리, 사용자 목표 거리, 추가 허용 거리 등.
3. 제한 수치와 근거는 무엇인가: 30%를 그대로 확정하지 말고 경로 사례와 사용자 의도를 검토한다.
4. 초과 시 무엇을 반환할 것인가: 선호 경로 유지·안내, 두 경로를 선택지로 제공, 선호 완화 후
   재탐색, 거리 경로 대체 중 어떤 방식을 사용할지 정한다.
5. 기준 경로 실패와 점수 부족 시 무엇을 안내하며, 선호 적용 여부를 어떻게 표현할 것인가.

Beam 구간은 사용자가 의도한 산책 거리를 채운다. 예를 들어 집→공원은 안전 연결,
공원→카페는 3km 산책인 요청을 전체 최단거리와 비교하면 의도한 산책을 잘라낼 수 있다.
이 요청에 실험 정책을 연결하려면 먼저 산책 목표를 보존하는 기준을 합의해야 한다.

## PR에 남길 설명

우회 상한 구현은 삭제하지 않고 팀 검토용 실험으로 보존했습니다. 30% 초과 시 사용자
선호를 버리고 최단으로 강제 대체하는 동작은 일반 요청에서 해제했습니다. 실험은 Composer에
비율을 명시할 때만 실행되며 운영 설정/API로 활성화되지 않습니다. 설문 기본값과 대화 선호의
기존 혼합 계산은 유지하고, 선호 탐색 실패로 거리 경로를 반환하면 적용 실패 사유를 표시합니다.
팀에서 우회 제한의 필요성·기준·초과 시 동작을 합의한 뒤 재사용할 수 있습니다.
