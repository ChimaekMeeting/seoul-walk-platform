# 데이터 intake 기록

draft_dataset.py가 registry.yaml에 draft를 등록할 때마다 자동으로 추가하는 기록입니다. 이 기록은 draft이며 실제 적재/score/profile 반영이 아닙니다.

<!-- intake-record:street_tree:start -->
## street_tree

- file: 전국가로수길정보표준데이터.csv
- approved: False
- source_type: csv
- geometry: LINESTRING
- city_filter: 제공기관명 = 서울
- score_column: nature_score
- score_effect: bonus
- profiles: nature, healing
- ai_expression: 가로수가 있는 길을 일부 반영할 수 있음
- rows: 10333
- missing_coordinates: 0
- invalid_coordinates: 0
- duplicate_coordinates: 1040
- seoul_bbox_outliers: 9035
- note: 이 기록은 draft이며 실제 적재/score/profile 반영이 아닙니다.
<!-- intake-record:street_tree:end -->
