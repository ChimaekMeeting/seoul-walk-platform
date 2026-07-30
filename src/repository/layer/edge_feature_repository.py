from sqlalchemy import delete, insert, text

from src.database.postgresql import engine, get_postgresql_db
from src.entity.layer.edge_feature_layer import EdgeFeatureLayer


class EdgeFeatureRepository:
    @staticmethod
    def replace_source(source_name: str, records: list[dict]) -> None:
        if not records:
            raise ValueError(f"{source_name} 선형 원본이 비어 있습니다.")

        with get_postgresql_db() as db:
            db.execute(
                delete(EdgeFeatureLayer).where(
                    EdgeFeatureLayer.source_name == source_name
                )
            )
            db.execute(insert(EdgeFeatureLayer), records)
            db.commit()

        with engine.begin() as connection:
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS idx_edge_feature_layer_geom "
                "ON edge_feature_layer USING GIST(geom)"
            ))
