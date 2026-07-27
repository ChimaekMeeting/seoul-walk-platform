# 백엔드 영역 계약 커버리지

> 상태: Current  
> 기준일: 2026-07-27  
> 관련 코드: `src/` 중 `frontend/**`를 제외한 백엔드

## 목적

작업 배분·통합 담당자가 실제 백엔드 영역과 Current 계약의 유무만 빠르게 확인하는 표다. 일반 도메인 작업자의 필수 읽기 문서가 아니다. 영역 분류 기준은 [문서 작성 및 관리 규칙](../documentation_guide.md)에서 관리한다.

## 계약 현황

| 영역 | Current 계약 | 상태 |
|---|---|---|
| 서버 runtime | `system_overview.md`, `operations/backend_runtime.md` | 있음 |
| 인증·Kakao 로그인 | `authentication/README.md` | 있음 |
| 사용자·설문·선호 | 없음 | 필요 |
| 직접 경로 서비스 | 엔진·Graph 계약만 있음 | 서비스 계약 필요 |
| 챗봇 | `chatbot/README.md`, `chatbot/agent_harness.md` | 있음 |
| 지도 조회 | 없음 | 필요 |
| 날씨·배너 | 없음 | 필요 |
| 데이터 적재 | `data/` 문서군 | 있음 |
| 경로 엔진·Graph | `route_engine/` 문서군 | 있음 |
| 좌표 보호 | 없음 | 필요 |
| PostgreSQL·Valkey 상태 저장 | 영역 문서에 일부 분산 | 공통 계약 필요 |
| 외부 API adapter | 영역 문서에 일부 분산 | 영역 계약 작성 후 판단 |

## 다음 작성 순서

사용자·설문·선호 → 직접 경로 서비스 → 지도 조회 → 날씨·배너 → 좌표 보호 → 상태 저장

새 계약을 코드와 대조해 확정하면 이 표의 문서 경로와 상태만 갱신한다. 참여 파일·입출력·복구 내용은 각 영역 계약에 두며 이 표에 추가하지 않는다.
