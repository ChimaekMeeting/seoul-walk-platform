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

## 2. 파일명과 제목

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

## 3. 문서 상태

```markdown
> 상태: Current
> 기준일: YYYY-MM-DD
> 관련 코드: `src/...`
```

- `Current`: 현재 구현과 일치
- `Proposal`: 아직 구현되지 않은 제안
- `Archive`: 현재 기준이 아닌 과거 기록

`README.md`와 분석 노트북은 상태 표시를 생략할 수 있습니다.

## 4. README 사용

`README.md`는 폴더의 문서 입구가 필요할 때만 만듭니다. 코드 폴더마다 반복해서 만들지 않고 `docs/{domain}/`에서 관리합니다.

## 5. 문서 유형 선택

문서 수를 늘리기 전에 무엇을 설명하려는지 먼저 구분합니다.

| 확인하려는 내용 | 사용할 문서 | 형식 |
|---|---|---|
| 한 영역의 책임·입출력·변경 경계 | `docs/{domain}/`의 영역 계약 | 공통 10개 항목 |
| 여러 영역을 통과하는 API·배치 흐름 | `docs/architecture/workflows/` | Workflow 6개 항목 |
| 실행·테스트·장애 복구 절차 | `docs/operations/` | 명령과 정상·실패 기준 |
| 아직 구현하지 않은 구조 | `docs/proposals/` | `Proposal` 상태 |
| 실험 과정과 판단 근거 | `analysis/` | 재현에 필요한 자유 형식 |

영역 계약은 독립 작업 단위의 경계를 정의하고, Workflow는 여러 영역 계약이 실제 요청에서 연결되는 순서를 검증합니다. 같은 책임·입력·의존성을 두 문서에 반복하지 않고 서로 링크합니다.

## 6. 영역 문서 공통 형식

모든 영역 문서는 [영역 계약 템플릿](templates/domain_contract.md)을 사용합니다.
새로운 영역 문서를 만들 때 구조를 다시 고민하지 않고 domain_contract.md를 복사해 내용만 채우면 됩니다.

```text
책임 → 입력 → 출력 → 실행 진입점 → 의존 영역 → 전달 영역
→ 변경 영향 → 실패·복구 → 검증 → 완료 기준
```

항목이 현재 영역에 해당하지 않으면 삭제하지 않고 `해당 없음`과 그 이유를 작성합니다.

## 7. 작성 원칙

1. 현재 사실, 실험 근거와 미래 제안을 섞지 않습니다.
2. 같은 기준은 한 문서에서만 관리하고 다른 문서는 링크합니다.
3. 실행 명령은 실제 동작을 확인한 뒤 기록합니다.
4. 수치에는 확인 날짜 또는 기준 커밋을 기록합니다.
5. 코드 변경으로 계약이나 실행법이 달라지면 문서도 함께 수정합니다.
6. 문서 이동·삭제 후 기존 링크가 남지 않았는지 확인합니다.
