import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from sqlalchemy import text
from src.database.postgresql import engine

with engine.begin() as conn:
    print("1단계: 전체 nature_score 1.0으로 초기화...", flush=True)
    conn.execute(text("UPDATE walk_edges SET nature_score = 1.0"))
    print("완료", flush=True)

with engine.begin() as conn:
    print("2단계: 녹지 근처 엣지만 업데이트 중...", flush=True)
    result = conn.execute(text("""
        UPDATE walk_edges we
        SET nature_score = best.score
        FROM (
            SELECT we2.link_id,
                   MAX(
                       CASE
                           WHEN ST_DWithin(og.geometry, we2.geom, 0.00027) THEN 1.0 + (og.green_weight / 3.0)
                           WHEN ST_DWithin(og.geometry, we2.geom, 0.0009)  THEN 1.0 + (og.green_weight / 3.0) * 0.6
                           WHEN ST_DWithin(og.geometry, we2.geom, 0.00225) THEN 1.0 + (og.green_weight / 3.0) * 0.3
                       END
                   ) AS score
            FROM walk_edges we2
            JOIN osm_green_areas og ON ST_DWithin(og.geometry, we2.geom, 0.00225)
            GROUP BY we2.link_id
        ) best
        WHERE we.link_id = best.link_id
    """))
    print(f"완료: {result.rowcount}개 엣지 업데이트", flush=True)
