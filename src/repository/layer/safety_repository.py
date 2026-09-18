from typing import List

import pandas as pd
from shapely.wkt import loads as wkt_loads
from sqlalchemy import delete, func, insert, select, bindparam, text

from src.database.postgresql import get_postgresql_db
from src.entity.layer.safety_layer import SafetyLayer
from src.repository.utils import RepositoryUtils


class SafetyRepository:
    # CCTV 설치목적 중 보행자 안전과 무관한 유형(교통단속·교통정보수집·차량방범)은
    # 안전 점수 집계에서 제외한다. purpose는 이 필터링을 위해 보존해 둔 값이다.
    EXCLUDED_CCTV_PURPOSES: set[str] = {"교통단속", "교통정보수집", "차량방범"}

    # 보안등 데이터 자체가 없는 자치구. 이 5개 구는 CCTV만으로 커버리지를 계산하고,
    # 나머지 20개 구는 CCTV+security_light를 함께 쓴다.
    CCTV_ONLY_GU: set[str] = {"강남구", "용산구", "마포구", "도봉구", "성동구"}

    @staticmethod
    def get(lat: float, lon: float, radius_m: int = 2000) -> pd.DataFrame:
        """
        반경 내 안전 시설물 포인트 전체를 조회합니다.
        safety_type(예: cctv, streetlight)을 category로 노출합니다.
        """
        return RepositoryUtils.fetch_nearby_points(
            SafetyLayer, lat, lon, radius_m, category_col=SafetyLayer.safety_type,
        )

    @staticmethod
    def save_all(records: List[dict]):
        """
        안전 시설물 데이터를 safety_layer에 벌크 저장합니다. 이미 같은 경위도가 있으면 스킵합니다.
        """
        if not records:
            return
        with get_postgresql_db() as db:
            rows = db.execute(
                select(func.ST_Y(SafetyLayer.geom).label("lat"), func.ST_X(SafetyLayer.geom).label("lon"))
            ).fetchall()
            existing = {(round(float(r.lat), 6), round(float(r.lon), 6)) for r in rows}
            new_records = []
            for r in records:
                pt = wkt_loads(r["geom"].desc)
                if (round(pt.y, 6), round(pt.x, 6)) not in existing:
                    new_records.append(r)
            if not new_records:
                return
            db.execute(insert(SafetyLayer), new_records)
            db.commit()

    @staticmethod
    def replace_types(records: List[dict], safety_types: set[str]) -> None:
        """지정한 안전 유형만 현재 수집 결과로 원자적으로 교체합니다."""
        with get_postgresql_db() as db:
            db.execute(
                delete(SafetyLayer).where(
                    SafetyLayer.safety_type.in_(safety_types)
                )
            )
            if records:
                db.execute(insert(SafetyLayer), records)
            db.commit()

    @staticmethod
    def get_safety_coverage_by_edge(radius_m: int = 20) -> dict[int, float]:
        """
        CCTV(EXCLUDED_CCTV_PURPOSES 제외)·security_light를 반경 radius_m로 버퍼링해
        겹치는 원을 하나로 합친 뒤, Edge 길이 대비 교차 길이 비율을 Edge별로 계산합니다.
        CCTV_ONLY_GU에 속한 자치구는 보안등 데이터가 없어 CCTV만으로 계산합니다.

        버퍼(폴리곤)를 먼저 union으로 합쳐서 겹치는 면적을 dissolve한 뒤 Edge와
        딱 한 번만 교차시킵니다. 개별 버퍼를 Edge와 먼저 교차시킨 뒤 그 결과
        선분들을 union하면, 겹치는 구간의 교차 선분들이 부동소수점 오차로
        완전히 일치하지 않아 dissolve되지 않고 길이가 중복 합산될 수 있습니다
        (검증: 관악구 psql 대조 결과 순서를 바꾸기 전 0.7307, 바꾼 후 0.7058 —
        참고값 0.706과 일치). walk_edges 전체를 기준으로 하므로 커버리지가
        없는 Edge도 0.0으로 포함해 반환합니다.

        Returns:
            dict[int, float]: {link_id: coverage_ratio(0.0~1.0)} 형태의 딕셔너리.
        """
        query = text(
            """
            WITH coverage_by_edge AS (
                SELECT
                    edge.link_id,
                    LEAST(
                        1.0,
                        COALESCE(
                            ST_Length(
                                ST_Transform(
                                    ST_Intersection(
                                        edge.geom,
                                        ST_Union(
                                            ST_Buffer(safety.geom::geography, :radius_m)::geometry
                                        )
                                    ),
                                    5179
                                )
                            )
                            / NULLIF(
                                ST_Length(ST_Transform(edge.geom, 5179)),
                                0.0
                            ),
                            0.0
                        )
                    ) AS coverage_ratio
                FROM walk_edges AS edge
                LEFT JOIN seoul_administrative_boundary AS boundary
                  ON ST_Contains(boundary.geom, ST_Centroid(edge.geom))
                JOIN safety_layer AS safety
                  ON (
                       (boundary.name IN :cctv_only_gu AND safety.safety_type = 'cctv')
                    OR (
                         (boundary.name IS NULL OR boundary.name NOT IN :cctv_only_gu)
                         AND safety.safety_type IN ('cctv', 'security_light')
                       )
                     )
                 AND (safety.safety_type != 'cctv' OR safety.purpose NOT IN :excluded_purposes)
                 AND ST_DWithin(edge.geom::geography, safety.geom::geography, :radius_m)
                GROUP BY edge.link_id, edge.geom
            )
            SELECT edge.link_id, COALESCE(coverage.coverage_ratio, 0.0) AS coverage_ratio
            FROM walk_edges AS edge
            LEFT JOIN coverage_by_edge AS coverage ON coverage.link_id = edge.link_id
            """
        ).bindparams(
            bindparam("excluded_purposes", expanding=True),
            bindparam("cctv_only_gu", expanding=True),
        )

        with get_postgresql_db() as db:
            rows = db.execute(
                query,
                {
                    "radius_m": radius_m,
                    "excluded_purposes": list(SafetyRepository.EXCLUDED_CCTV_PURPOSES),
                    "cctv_only_gu": list(SafetyRepository.CCTV_ONLY_GU),
                },
            ).fetchall()

        return {row.link_id: float(row.coverage_ratio) for row in rows}
