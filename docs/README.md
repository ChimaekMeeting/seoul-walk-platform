# ROUDI 프로젝트 문서

프로젝트 구조, 영역별 계약과 실행 방법을 관리합니다. 문서를 추가하거나 이동할 때는 [문서 작성 규칙](documentation_guide.md)을 따릅니다.

## 읽는 순서

1. 루트 `README.md`: 프로젝트 소개와 로컬 실행
2. [전체 백엔드 시스템 구조](architecture/system_overview.md): 전체 영역과 연결 관계
3. 담당 영역의 `README.md`와 계약 문서
4. `operations/`: 실행·복구·검증 방법
5. `analysis/`: 실험 과정과 판단 근거

## 현재 문서 구조

```text
docs/                              // 프로젝트 문서
├── README.md                      // 전체 문서 지도
├── documentation_guide.md        // 문서 배치·이름·작성 규칙
├── architecture/                  // 전체 시스템 구조와 흐름
│   ├── system_overview.md         // 백엔드 작업 단위와 연결 관계
│   ├── system_workflows.md        // 전체 workflow 목록과 연결 지도
│   └── workflows/                 // 개별 workflow의 실행·실패·검증
│       ├── server_startup.md
│       ├── kakao_authentication.md
│       ├── walk_route_request.md
│       ├── prewalk_conversation.md
│       ├── map_environment_banner.md
│       └── v1_data_ingestion.md
├── chatbot/                       // 챗봇 영역
│   ├── README.md                  // 현재 구성요소와 실행 흐름
│   └── agent_harness.md           // State·Node·Edge·Tool 계약
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
├── proposals/                     // 아직 구현하지 않은 변경 제안
│   └── chatbot_upgrade_proposal.md // 챗봇 업그레이드 결정·작업 단위
├── templates/                     // 공통 문서 형식
│   └── domain_contract.md         // 영역별 계약 템플릿
└── route_engine/                  // 경로 생성 엔진
    ├── README.md                  // 엔진 구조와 영역 경계
    └── graph_contract.md          // NetworkX Graph 계약
```

영역별 입구:

- [전체 백엔드 시스템 구조](architecture/system_overview.md)
- [전체 Workflow 지도](architecture/system_workflows.md)
- [데이터](data/README.md)
- [챗봇](chatbot/README.md)
- [챗봇 Agent 하네스](chatbot/agent_harness.md)
- [챗봇 Agent 업그레이드 제안](proposals/chatbot_upgrade_proposal.md)
- [경로 생성 엔진](route_engine/README.md)
- [백엔드 실행 환경](operations/backend_runtime.md)
- [데이터 적재](operations/data_ingestion.md) · [V1 재구축](operations/data_rebuild.md) · [테스트](operations/testing.md)

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

## 작성 중

- `architecture/workflows/`: 코드와 실행 결과를 확인하며 개별 workflow 작성

## 구분 원칙

- 현재 구조·계약·실행 기준: `docs/`
- 실험 과정과 근거: `analysis/`
- 미구현 설계: `docs/proposals/`
- `frontend/`는 현재 문서 개편 범위에서 제외
