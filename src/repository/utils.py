import h3
from sqlalchemy import func


class RepositoryUtils:
    @staticmethod
    def geom_centroid_lat_lng(geom):
        centroid = func.ST_Centroid(geom)
        return func.ST_Y(centroid), func.ST_X(centroid)

    @staticmethod
    def lat_lng_to_h3(lat: float, lng: float, resolution: int = 9) -> str:
        return h3.latlng_to_cell(lat, lng, resolution)
