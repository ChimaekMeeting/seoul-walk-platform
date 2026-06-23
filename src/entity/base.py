from sqlalchemy import inspect, text
from sqlalchemy.orm import declarative_base
from src.database.postgresql import engine

Base = declarative_base()

def register_entities():
    """
    Base.metadata에 모든 엔티티 테이블 정보를 등록합니다.
    """
    from src.entity import chat_session, user, user_preference, banner
    from src.entity.network import walk_node, walk_edge
    from src.entity.layer import (
        safety_layer,
        landmark_layer,
        nature_layer,
        running_layer,
        child_layer,
        seoul_administrative_boundary,
        seoul_water_polygon,
    )
    from src.entity.raw import osm_raw, kakao_raw, public_raw, csv_raw

def init_table():
    """
    테이블이 없으면 생성하고, 있으면 entity 정의와 컬럼을 동기화합니다.
    """
    inspector = inspect(engine)

    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not inspector.has_table(table.name):
                table.create(bind=engine)
                continue

            existing = {col["name"] for col in inspector.get_columns(table.name)}
            defined  = {col.name: col for col in table.columns}

            for col_name, col in defined.items():
                if col_name not in existing:
                    # Postgres ENUM 등 별도 생성이 필요한 타입(SchemaType)을 먼저 만든 뒤 컬럼을 추가합니다.
                    if hasattr(col.type, "create"):
                        col.type.create(bind=conn, checkfirst=True)
                    col_type = col.type.compile(engine.dialect)
                    conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col_name}" {col_type}'))

            for col_name in existing:
                if col_name not in defined:
                    conn.execute(text(f'ALTER TABLE "{table.name}" DROP COLUMN "{col_name}"'))

def init_db():
    """
    테이블 생성을 위한 초기화 함수입니다.
    """
    register_entities()
    init_table()

    from src.repository.banner.banner_repository import BannerRepository
    BannerRepository.seed()
