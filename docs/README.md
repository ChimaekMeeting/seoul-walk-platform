# ROUDI 프로젝트 문서

프로젝트 구조, 영역별 계약과 실행 방법을 관리합니다. 문서를 추가하거나 이동할 때는 [문서 작성 규칙](documentation_guide.md)을 따릅니다.

## 처음 온 팀원

처음 합류할 때만 루트 `README.md`와 [전체 백엔드 시스템 구조](architecture/system_overview.md)를 읽습니다.

그다음부터는 Notion·Issue 등 업무 카드에 적힌 담당 영역의 시작 문서 하나만 읽습니다.

| 담당 업무 | 시작 문서 |
|---|---|
| 인증·Kakao 로그인 | [authentication/README.md](authentication/README.md) |
| Cloud Run 배포 | [deployment/README.md](deployment/README.md) |
| 챗봇 | [chatbot/README.md](chatbot/README.md) |
| 데이터 | [data/README.md](data/README.md) |
| 경로 엔진·Graph | [route_engine/README.md](route_engine/README.md) |

추가 문서는 작업 성격에 따라 필요한 경우에만 읽습니다.

| 이런 작업일 때만 | 추가로 읽을 문서 |
|---|---|
| 여러 영역의 연결을 변경 | 관련 [Workflow](architecture/system_workflows.md) |
| 서버 실행·테스트·데이터 복구 | 업무 카드에 지정된 `operations/` 문서 |
| 새 영역을 나누거나 전체 문서를 통합 | [영역 계약 커버리지](architecture/backend_domain_coverage.md), 문서 작성 규칙 |

`docs/` 전체를 먼저 읽지 않습니다. 담당자·브랜치·이번 주 업무는 저장소가 아니라 팀 업무 보드에서 관리하고, 업무 카드에는 `담당 영역`, `수정 범위`, `시작 문서`를 적습니다.

## 현재 문서 구조

```text
docs/                              // 프로젝트 문서
├── README.md                      // 전체 문서 지도
├── documentation_guide.md        // 문서 배치·이름·작성 규칙
├── architecture/                  // 전체 시스템 구조와 흐름
│   ├── system_overview.md         // 백엔드 작업 단위와 연결 관계
│   ├── backend_domain_coverage.md // 문서 통합 담당자의 계약 누락 현황
│   ├── system_workflows.md        // 전체 workflow 목록과 연결 지도
│   └── workflows/                 // 개별 workflow의 실행·실패·검증
│       ├── server_startup.md
│       ├── kakao_authentication.md
│       ├── walk_route_request.md
│       ├── prewalk_conversation.md
│       ├── map_environment_banner.md
│       └── v1_data_ingestion.md
├── authentication/                // 인증·Kakao 로그인 영역
│   └── README.md                  // JWT·cookie·Valkey 계약
├── chatbot/                       // 챗봇 영역
│   ├── README.md                  // 현재 구성요소와 실행 흐름
│   ├── agent_harness.md           // State·Node·Edge·Tool 계약
│   └── test_scenarios.md          // 수동 테스트 스크립트 시나리오와 실행 결과
├── data/                          // 데이터 영역
│   ├── README.md                  // V1 범위와 상세 문서 안내
│   ├── data_score_mapping.md      // 원본·Layer·Score 연결
│   ├── dataset_roles.md           // RAW 역할·품질·사용 상태
│   └── walk_network_contract.md   // NODE·LINK 적재 계약
├── operations/                    // 실행·복구·검증
│   ├── backend_runtime.md         // 팀 공통 백엔드 실행 환경
│   ├── data_ingestion.md          // 데이터 적재 절차
│   ├── data_rebuild.md            // V1 전체 재구축·검증·복구
│   └── testing.md                 // 테스트 작성 구조
├── deployment/                    // Cloud Run 배포 영역
│   └── README.md                  // Docker·cloudbuild·시크릿·마이그레이션 계약
├── proposals/                     // 아직 구현하지 않은 변경 제안
│   ├── chatbot_upgrade_proposal.md // 챗봇 업그레이드 결정·작업 단위
│   ├── chatbot_cleanup_proposal.md // 챗봇 불필요한 항목 제거 발견 목록
│   └── chatbot_hardcoding_proposal.md // 챗봇 하드코딩 문구 처리 방안
├── templates/                     // 공통 문서 형식
│   ├── domain_contract.md         // 영역별 계약 템플릿
│   └── work_unit.md               // 업무 배정자가 사용하는 범위·인계 양식
└── route_engine/                  // 경로 생성 엔진
    ├── README.md                  // 엔진 구조와 영역 경계
    └── graph_contract.md          // NetworkX Graph 계약
```

## 문서 종류별 입구

도메인 작업:

- [인증·Kakao 로그인](authentication/README.md)
- [Cloud Run 배포](deployment/README.md)
- [데이터](data/README.md)
- [챗봇](chatbot/README.md)
- [챗봇 Agent 하네스](chatbot/agent_harness.md)
- [챗봇 Prewalk 대화 테스트 시나리오](chatbot/test_scenarios.md)
- [경로 생성 엔진](route_engine/README.md)

실행·복구 작업:

- [백엔드 실행 환경](operations/backend_runtime.md)
- [데이터 적재](operations/data_ingestion.md) · [V1 재구축](operations/data_rebuild.md) · [테스트](operations/testing.md)

통합·문서 관리:

- [전체 백엔드 시스템 구조](architecture/system_overview.md)
- [백엔드 영역 계약 커버리지](architecture/backend_domain_coverage.md)
- [전체 Workflow 지도](architecture/system_workflows.md)
- [문서 작성 규칙](documentation_guide.md)
- [챗봇 Agent 업그레이드 제안](proposals/chatbot_upgrade_proposal.md)
- [챗봇 Agent 불필요한 항목 제거 제안](proposals/chatbot_cleanup_proposal.md)
- [챗봇 Agent 하드코딩 문구 처리 방안 제안](proposals/chatbot_hardcoding_proposal.md)

## 전체 하네스 문서화 순서

```text
전체 백엔드 작업 단위 조사
→ system_overview 작성
→ 주요 흐름을 system_workflows로 작성
→ 모든 영역을 같은 계약 형식으로 문서화
→ 실행·테스트·복구 연결
→ 챗봇 State·Node·Edge·Tool 상세화
```

영역 문서는 [영역 계약 템플릿](templates/domain_contract.md)을 사용합니다.

## 다음 문서화 범위

- `system_overview.md`와 6개 주요 Workflow는 현재 코드·실행 결과 기준으로 작성했다.
- 다음 단계는 Workflow에 참여하지만 독립 영역 계약이 없는 백엔드 작업 단위를 확인하고 같은 계약 형식으로 문서화하는 것이다.

## 구분 원칙

- 현재 구조·계약·실행 기준: `docs/`
- 실험 과정과 근거: `analysis/`
- 미구현 설계: `docs/proposals/`
- `frontend/`는 현재 문서 개편 범위에서 제외
