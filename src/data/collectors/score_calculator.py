import math
from sqlalchemy import text
from src.database.postgresql import engine


def calculate_scores():
    with engine.connect() as conn:
        result = conn.execute(text("""
            WITH edge_cells AS (
                SELECT
                    link_id,
                    h3_lat_lng_to_cell(ST_Centroid(geom)::geometry, 9) AS h3_cell
                FROM walk_edges
            ),
            safety_counts AS (
                SELECT
                    h3_lat_lng_to_cell(geom::geometry, 9) AS h3_cell,
                    COUNT(*) AS cnt
                FROM safety_layer
                GROUP BY h3_cell
            ),
            nature_counts AS (
                SELECT
                    h3_lat_lng_to_cell(geom::geometry, 9) AS h3_cell,
                    COUNT(*) AS cnt
                FROM poi_layer
                GROUP BY h3_cell
            )
            SELECT
                e.link_id,
                COALESCE(s.cnt, 0) AS safety_cnt,
                COALESCE(n.cnt, 0) AS nature_cnt
            FROM edge_cells e
            LEFT JOIN safety_counts s ON e.h3_cell = s.h3_cell
            LEFT JOIN nature_counts n ON e.h3_cell = n.h3_cell
        """))

        rows = result.fetchall()

        if not rows:
            print("walk_edges 데이터 없음")
            return

        safety_log = [math.log(r.safety_cnt + 1) for r in rows]
        nature_log = [math.log(r.nature_cnt + 1) for r in rows]

        safety_max = max(safety_log) or 1.0
        nature_max = max(nature_log) or 1.0

        updates = [
            {
                "link_id": row.link_id,
                "safety_score": 1.0 + safety_log[i] / safety_max,
                "nature_score": 1.0 + nature_log[i] / nature_max,
            }
            for i, row in enumerate(rows)
        ]

        conn.execute(text("""
            UPDATE walk_edges
            SET safety_score = :safety_score, nature_score = :nature_score
            WHERE link_id = :link_id
        """), updates)

        conn.commit()
        print(f"[완료] {len(updates)}개 엣지 score 업데이트")


if __name__ == "__main__":
    calculate_scores()