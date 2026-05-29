from pydantic import BaseModel, ConfigDict

from src.entity.layer.safety_layer import SafetyLayer
from src.entity.layer.nature_layer import NatureLayer
from src.entity.layer.landmark_layer import LandmarkLayer


class LayerEntityMap(BaseModel):
    """
    레이어 테이블명과 SQLAlchemy 엔티티 클래스의 매핑을 관리합니다.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    safety_layer:   type = SafetyLayer
    nature_layer:   type = NatureLayer
    landmark_layer: type = LandmarkLayer
