# Raw Data Analysis

Raw 레이어 대시보드 구현을 위한 분석 산출물을 관리합니다.

## Files

- `raw_layer_mapping.ipynb`: 현재 실제 layer에 쓰이는 raw 데이터 중심 매핑 및 시각화 노트북
- `walk_network_external_overlap_validation.ipynb`: 도보 네트워크의 횡단보도, 육교, 터널, 공원/녹지 속성이 외부 RAW 데이터와 공간적으로 일치하는지 검증하는 노트북

## Scope

- 현재 파이프라인에서 실제 layer/score에 반영되는 raw 데이터를 우선 시각화합니다.
- 비활성, draft, raw-only 데이터는 대시보드 본문이 아니라 참고 메모로만 다룹니다.

## Memo

이번 분석에서는 외부 RAW 데이터를 바로 새로운 layer/score로 연결하지 않는다.
먼저 도보 네트워크 자체에 존재하는 횡단보도, 육교, 터널, 공원/녹지 등 속성이 외부 RAW 데이터와 공간적으로 일치하는지 검증한다.

외부 RAW 데이터는 다음 세 가지 관점으로 분류한다.

1. 기존 도보 네트워크 속성의 신뢰도 검증용
2. 기존 속성에 없는 구간을 보강하는 layer 후보
3. 기존 데이터와 충돌하거나 품질이 낮아 보류할 데이터
