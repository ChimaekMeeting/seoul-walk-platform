import h3
from sqlalchemy import func


class RepositoryUtils:
    @staticmethod
    def geom_centroid_lat_lon(geom):
        centroid = func.ST_Centroid(geom)
        return func.ST_Y(centroid), func.ST_X(centroid)

    @staticmethod
    def lat_lon_to_h3(lat: float, lon: float, resolution: int = 9) -> str:
        return h3.latlng_to_cell(lat, lon, resolution)
