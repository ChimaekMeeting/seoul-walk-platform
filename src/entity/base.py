from sqlalchemy.orm import declarative_base
from src.database.postgresql import engine

Base = declarative_base()

def register_entities():
    """
    Base.metadata에 모든 엔티티 테이블 정보를 등록합니다.
    """
    from src.entity import chat_session, user
    from src.entity.network import walk_node, walk_edge
    from src.entity.layer import (
        safety_layer,
        landmark_layer,
        nature_layer,
        running_layer,
        child_layer
    )


def init_db():
    """
    테이블 생성을 위한 초기화 함수입니다.
    """
    register_entities()
    Base.metadata.create_all(bind=engine)
