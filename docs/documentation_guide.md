# 문서 작성 및 관리 규칙

> 상태: Current  
> 적용 범위: 프로젝트의 Markdown 문서와 분석 산출물

## 1. 문서 위치

| 내용 | 위치 |
|---|---|
| 프로젝트 소개 | `/README.md` |
| 전체 문서 지도 | `docs/README.md` |
| 시스템 구조 | `docs/architecture/` |
| 영역별 계약 | `docs/{domain}/` |
| 실행·복구·테스트 | `docs/operations/` |
| 미구현 제안 | `docs/proposals/` |
| 실험 과정과 근거 | `analysis/` |
| RAW 원본 정의 | `src/data/raw/metadata/` |

`frontend/`는 모바일 프론트엔드 연결 후 별도로 정리합니다.

## 2. 영역 분류 원칙

`docs/{domain}/`은 `src`의 최상위 폴더를 그대로 복제하지 않는다. 독립적으로 변경·검증·복구할 책임과 실행 진입점이 있는 작업 단위를 영역으로 정한다.

영역 여부는 다음 순서로 판단한다.

1. Router, Service, 배치 명령처럼 실제 실행 진입점이 있는가
2. 고유한 입력·출력과 저장 상태를 소유하는가
3. 다른 영역과 구분되는 실패·복구 경계가 있는가
4. 변경 결과를 독립적으로 검증할 수 있는가

`entity`, `repository`, `infrastructure`, `interfaces`, `schema`처럼 여러 책임이 공유하는 기술 계층은 같은 이름의 문서 영역을 반복해서 만들지 않는다. 해당 코드의 입력·출력과 변경 영향은 실제 책임을 소유한 영역 계약에 포함한다.

폴더가 비어 있거나 `__pycache__`만 있고 현재 호출자가 없는 경우에는 미래 구조를 추정해 Current 영역으로 등록하지 않는다.

실제 백엔드 영역, 참여 코드, 계약 문서와 작성 상태의 단일 기준은 [백엔드 영역 계약 커버리지](architecture/backend_domain_coverage.md)에서 관리한다. 새 영역 문서를 만들기 전 이 표에서 기존 계약과 중복되는지 먼저 확인하고, 작성·검증을 마치면 상태를 함께 갱신한다.

## 3. 파일명과 제목

| 구분 | 규칙 | 예시 |
|---|---|---|
| 파일명 | 영문 소문자 `snake_case` | `documentation_guide.md` |
| 첫 번째 `#` 제목 | 역할을 바로 이해할 수 있는 한글 중심 제목 | `# 문서 작성 및 관리 규칙` |

기술 용어(`RAW`, `API`, `State`, `Node`, `Edge`, `Tool`)와 공식 데이터셋 이름은 그대로 사용할 수 있습니다.

| 종류 | 이름 | 예시 |
|---|---|---|
| 폴더 입구 | `README.md` | `docs/data/README.md` |
| 구조 | `{scope}_overview.md` | `system_overview.md` |
| 계약 | `{subject}_contract.md` | `walk_network_contract.md` |
| 실행 | `{action}.md` | `data_rebuild.md` |
| 하네스 | `{subject}_harness.md` | `agent_harness.md` |
| 제안 | `{subject}_proposal.md` | `route_engine_proposal.md` |
| 분석 | `{subject}_validation.*` | `park_mapping_validation.ipynb` |

`plan.md`, `memo.md`, `정리.md`처럼 역할이 불분명한 이름은 사용하지 않습니다.

## 4. 문서 상태

```markdown
> 상태: Current
> 기준일: YYYY-MM-DD
> 관련 코드: `src/...`
```

- `Current`: 현재 구현과 일치
- `Proposal`: 아직 구현되지 않은 제안
- `Archive`: 현재 기준이 아닌 과거 기록

`README.md`와 분석 노트북은 상태 표시를 생략할 수 있습니다.

## 5. README 사용

`README.md`는 폴더의 문서 입구가 필요할 때만 만듭니다. 코드 폴더마다 반복해서 만들지 않고 `docs/{domain}/`에서 관리합니다.

## 6. 문서 유형 선택

문서 수를 늘리기 전에 무엇을 설명하려는지 먼저 구분합니다.

| 확인하려는 내용 | 사용할 문서 | 형식 |
|---|---|---|
| 한 영역의 책임·입출력·변경 경계 | `docs/{domain}/`의 영역 계약 | 공통 10개 항목 |
| 여러 영역을 통과하는 API·배치 흐름 | `docs/architecture/workflows/` | Workflow 6개 항목 |
| 실행·테스트·장애 복구 절차 | `docs/operations/` | 명령과 정상·실패 기준 |
| 아직 구현하지 않은 구조 | `docs/proposals/` | `Proposal` 상태 |
| 실험 과정과 판단 근거 | `analysis/` | 재현에 필요한 자유 형식 |

영역 계약은 독립 작업 단위의 경계를 정의하고, Workflow는 여러 영역 계약이 실제 요청에서 연결되는 순서를 검증합니다. 같은 책임·입력·의존성을 두 문서에 반복하지 않고 서로 링크합니다.

## 7. 영역 문서 공통 형식

모든 영역 문서는 [영역 계약 템플릿](templates/domain_contract.md)을 사용합니다.
새로운 영역 문서를 만들 때 구조를 다시 고민하지 않고 domain_contract.md를 복사해 내용만 채우면 됩니다.

```text
책임 → 입력 → 출력 → 실행 진입점 → 의존 영역 → 전달 영역
→ 변경 영향 → 실패·복구 → 검증 → 완료 기준
```

항목이 현재 영역에 해당하지 않으면 삭제하지 않고 `해당 없음`과 그 이유를 작성합니다.

## 8. 작성 원칙

1. 현재 사실, 실험 근거와 미래 제안을 섞지 않습니다.
2. 같은 기준은 한 문서에서만 관리하고 다른 문서는 링크합니다.
3. 실행 명령은 실제 동작을 확인한 뒤 기록합니다.
4. 수치에는 확인 날짜 또는 기준 커밋을 기록합니다.
5. 코드 변경으로 계약이나 실행법이 달라지면 문서도 함께 수정합니다.
6. 문서 이동·삭제 후 기존 링크가 남지 않았는지 확인합니다.

## 9. 작업별 문서 읽기

담당자·브랜치·이번 주 업무는 Notion·Issue 등 팀 업무 보드에서 관리한다. 일반 업무 카드에는 `담당 영역`, `수정 범위`, `시작 문서`만 지정한다.

[작업 단위 계약 템플릿](templates/work_unit.md)은 여러 영역을 동시에 변경하거나 데이터 재구축처럼 영향·복구·인계 조건을 별도로 합의해야 하는 작업에서만 선택적으로 사용한다.

팀원은 `docs/` 전체를 읽지 않는다. 업무 카드에 지정된 시작 문서를 먼저 읽고, 팀원이 문서 종류를 보고 추가 문서를 스스로 모두 찾아 읽는 방식이 아니다.

| 작업 종류 | 보통 지정하는 문서 |
|---|---|
| 한 영역 내부 변경 | 담당 영역 계약 1개 |
| 여러 영역의 연결 변경 | 담당 영역 계약 + 지정된 Workflow 1개 |
| 특정 실행·복구 작업 | 지정된 `operations/` 문서 1개, 필요하면 담당 계약 |
| 새 영역 조사·작업 배분 | `system_overview.md` + `backend_domain_coverage.md` |
| 문서 추가·이동 | `documentation_guide.md` + `docs/README.md` |
| 전체 통합 | `system_overview.md` + 통합 대상 계약·Workflow |

`operations/`는 모든 도메인 작업의 세 번째 필수 문서가 아니다. 서버 실행, 데이터 재구축, 테스트 환경, 장애 복구처럼 명령과 정상·실패 기준이 필요한 작업에만 지정한다.

작업에 직접 관계없는 영역 문서는 읽지 않는다. 새로운 의존성이 확인되면 임의로 범위를 넓히지 않고 업무 카드나 PR에 기록한다.

## 10. 병렬 작업과 공유 문서

도메인별 코드와 계약 문서는 서로 다른 브랜치에서 병렬로 작업할 수 있다. 모든 문서를 하나의 문서 전용 브랜치에서 관리할 필요는 없다.

충돌이 잦은 다음 파일은 공유 문서로 취급한다.

- `docs/README.md`
- `docs/documentation_guide.md`
- `docs/architecture/system_overview.md`
- `docs/architecture/system_workflows.md`
- `docs/architecture/backend_domain_coverage.md`
- `docs/templates/`

병렬 작업 규칙:

1. 각 작업은 담당 도메인, 허용 코드 경로와 허용 문서 경로를 먼저 정한다.
2. 도메인 담당자는 자신의 `docs/{domain}/` 계약을 코드와 함께 갱신한다.
3. 같은 개별 Workflow는 한 시점에 한 명만 수정한다.
4. 공유 문서는 통합 담당자가 각 도메인 변경을 병합한 뒤 갱신한다.
5. 도메인 담당자는 공유 문서를 직접 수정하는 대신 필요한 변경을 업무 카드나 PR에 기록한다.
6. 병합 순서는 독립 도메인 → 관련 Workflow → 전체 지도·커버리지 순서로 한다.

공유 문서 수정이 작업 완료에 반드시 필요하면 업무 카드에 해당 파일의 임시 소유권을 명시한다.
