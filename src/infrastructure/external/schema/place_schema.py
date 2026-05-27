from pydantic import BaseModel


class PlaceInfo(BaseModel):
    """
    좌표를 주소로 변환한 결과를 나타냅니다.
    """
    place_address: str
    place_name: str
    place_lat: float
    place_lon: float


class PlaceDocument(BaseModel):
    """
    장소 검색 결과 목록의 개별 장소 항목을 나타냅니다.
    """
    place_name: str
    category_name: str
    address_name: str
    x: str  # 경도 (longitude)
    y: str  # 위도 (latitude)


class PlaceSearchMeta(BaseModel):
    """
    장소 검색 결과의 메타 정보를 나타냅니다.
    """
    is_end: bool


class PlaceSearchResult(BaseModel):
    """
    키워드 또는 카테고리 기반 장소 검색의 전체 응답을 나타냅니다.
    """
    documents: list[PlaceDocument]
    meta: PlaceSearchMeta