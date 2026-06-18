import math

import h3
import numpy as np
from sqlalchemy import func


class RepositoryUtils:
    @staticmethod
    def geom_centroid_lat_lon(geom):
        centroid = func.ST_Centroid(geom)
        return func.ST_Y(centroid), func.ST_X(centroid)

    @staticmethod
    def lat_lon_to_h3(lat: float, lon: float, resolution: int = 9) -> str:
        return h3.latlng_to_cell(lat, lon, resolution)


def serialize(val):
    """ORM insert 전 JSONB 직렬화 가능한 형태로 변환합니다."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return None if np.isnan(val) else float(val)
    if isinstance(val, (str, int, float, bool)):
        return val
    if isinstance(val, list):
        return [serialize(v) for v in val]
    return str(val)
