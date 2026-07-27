# 데이터 수집 및 적재

> 상태: Current  
> 기준일: 2026-07-24  
> 관련 코드: `src/data/`, `src/repository/network/`

데이터 영역의 V1 범위와 상세 문서를 안내합니다.

## V1 데이터 흐름

```text
서울시 도보 네트워크
→ WalkNode·WalkEdge
→ GraphRepository
→ NetworkX 속성·tags

서울시 공원 Polygon
→ nature_layer
→ WalkEdge.park_overlap_ratio
```

`raw_is_park_green`과 `park_overlap_ratio`는 별도 근거로 보존하며 `nature_score` 결합 정책은 아직 확정하지 않았습니다.

## 재적재 확인 결과

| 결과 | 건수 |
|---|---:|
| WalkNode / WalkEdge | 214,241 / 279,016 |
| 공원 Polygon / 중첩 Edge | 1,888 / 13,194 |
| 서울 경계 / 수계 Polygon | 1 / 411 |

## 상세 문서

| 문서 | 역할 |
|---|---|
| [도보 네트워크 계약](walk_network_contract.md) | 원본 NODE·LINK부터 NetworkX까지의 매핑 |
| [데이터 역할과 상태](dataset_roles.md) | RAW별 품질, 코드 연결과 V1 사용 여부 |
| [데이터와 Score 연결](data_score_mapping.md) | 원본·Layer·WalkEdge Score 연결 |
| [데이터 적재](../operations/data_ingestion.md) | V1 적재 및 upsert·rebuild 실행 |

RAW 코드표와 원본 정의는 `src/data/raw/metadata/`, 실험 근거는 `analysis/raw/`과 `analysis/layer/`에서 관리합니다.

## 관리 원칙

- 원본 보유와 V1 서비스 사용을 구분합니다.
- 새 속성은 원본 → DB → GraphRepository → NetworkX → 알고리즘까지 검증합니다.
- 기본 실행 범위는 `--scope v1`이며 과거 전체 파이프라인은 `--scope legacy-all`입니다.
