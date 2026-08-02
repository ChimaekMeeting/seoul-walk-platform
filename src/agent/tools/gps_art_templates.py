from src.schema.prewalk_schema import Point

# (0, 0)을 출발지로 하는 상대 좌표. 시작점과 끝점이 (0, 0)으로 같아 닫힌 도형이며,
# 다른 shape 추가 시 같은 방식으로 항목을 늘린다.
#
# 여기 저장된 점 개수는 상한선일 뿐이다 — 실제 경로 생성 시 target_km에 맞춰
# 다운샘플링되어 일부만 쓰인다(gps_art_proposal.md D7). 그래서 가능한 한 고해상도로
# 만드는 게 좋다(목표 90~100개 내외, scripts/extract_gps_art_template.py로 추출 가능).
# 아래 "강아지"는 다리4·몸통·머리로 손으로 그린 25점짜리 저해상도 placeholder이며,
# 고해상도 버전으로 교체가 필요하다.
GPS_ART_TEMPLATES: dict[str, list[Point]] = {
    "강아지": [
        Point(x=0, y=0), Point(x=1, y=0), Point(x=1, y=3), Point(x=2, y=3),
        Point(x=2, y=0), Point(x=3, y=0), Point(x=3, y=3), Point(x=5, y=3),
        Point(x=5, y=0), Point(x=6, y=0), Point(x=6, y=3), Point(x=7, y=3),
        Point(x=7, y=0), Point(x=8, y=0), Point(x=8, y=3), Point(x=8, y=4),
        Point(x=10, y=4), Point(x=10, y=7), Point(x=8, y=7), Point(x=8, y=6),
        Point(x=5, y=7), Point(x=2, y=6), Point(x=0, y=6), Point(x=0, y=3),
        Point(x=0, y=0),
    ],
}
