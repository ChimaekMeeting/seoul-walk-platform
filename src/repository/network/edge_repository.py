import pandas as pd
from sqlalchemy import func, select, update, insert, inspect, text, cast
from geoalchemy2 import Geography
from src.database.postgresql import get_postgresql_db, engine
from src.entity.network.walk_edge import WalkEdge
from typing import List


class EdgeRepository:
    @staticmethod
    def truncate():
        """
        walk_edges 테이블의 모든 데이터를 초기화합니다.
        시퀀스(ID)도 함께 리셋하며, 연관 테이블에 CASCADE 적용합니다.
        """
        with engine.begin() as conn:
            conn.execute(text("TRUNCATE TABLE walk_edges RESTART IDENTITY CASCADE"))

    @staticmethod
    def save_all(edges: List[dict], chunksize: int = 10000):
        """
        엣지 데이터를 청크 단위로 walk_edges에 벌크 저장합니다.

        Args:
            edges     : 저장할 엣지 딕셔너리 목록.
            chunksize : 한 번에 삽입할 레코드 수. 기본값 10,000.
        """
        existing_cols = {col["name"] for col in inspect(engine).get_columns("walk_edges")}
        score_defaults = {
            col.name: float(col.server_default.arg)
            for col in WalkEdge.__table__.columns
            if col.server_default is not None and col.name in existing_cols
        }
        with get_postgresql_db() as db:
            for i in range(0, len(edges), chunksize):
                chunk = [{**score_defaults, **e} for e in edges[i:i + chunksize]]
                db.execute(insert(WalkEdge), chunk)
            db.commit()

    @staticmethod
    def ensure_score_column(name: str):
        """
        walk_edges 테이블에 스코어 컬럼이 없으면 추가합니다.

        Args:
            name : 추가할 컬럼명. 예: 'nature_score', 'landmark_score'.
        """
        columns = [col["name"] for col in inspect(engine).get_columns("walk_edges")]
        if name not in columns:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE walk_edges ADD COLUMN {name} FLOAT DEFAULT 0.0"))

    @staticmethod
    def get_link_h3_cells() -> list:
        """
        각 엣지의 중심점을 H3 셀(resolution 9)로 변환한 (link_id, h3_cell) 목록을 반환합니다.

        Returns:
            list: (link_id, h3_cell) 튜플 리스트.
        """
        with get_postgresql_db() as db:
            h3_expr = func.h3_lat_lng_to_cell(func.ST_Centroid(WalkEdge.geom), 9)
            rows = db.execute(
                select(WalkEdge.link_id, h3_expr.label("h3_cell"))
            ).fetchall()
            return rows

    @staticmethod
    def update_scores(updates: List[dict]):
        """
        엣지별 스코어 값을 일괄 업데이트합니다.

        Args:
            updates : 업데이트할 딕셔너리 목록. 각 항목은 link_id와 변경할 스코어 필드를 포함해야 합니다.
        """
        with get_postgresql_db() as db:
            db.execute(update(WalkEdge), updates)
            db.commit()

    @staticmethod
    def fetch_nearby_lines(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        주어진 좌표 반경 내의 도보 네트워크 라인 데이터를 조회합니다.

        Args:
            lat      : 중심 위도.
            lon      : 중심 경도.
            radius_m : 탐색 반경(미터). 기본값 2,000.

        Returns:
            pd.DataFrame: geometry(GeoJSON 문자열), link_id 컬럼을 포함한 데이터프레임.
        """
        center = cast(func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326), Geography())
        try:
            with get_postgresql_db() as db:
                rows = db.execute(
                    select(
                        func.ST_AsGeoJSON(func.ST_Simplify(WalkEdge.geom, 0.00005)).label("geometry"),
                        WalkEdge.link_id,
                    ).where(
                        func.ST_DWithin(cast(WalkEdge.geom, Geography()), center, radius_m)
                    )
                ).fetchall()
            return pd.DataFrame(rows, columns=["geometry", "link_id"])
        except Exception as e:
            print(f"DB 라인 조회 실패: {e}")
            return pd.DataFrame()
