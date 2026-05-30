from sqlalchemy import func


class RepositoryUtils:
    @staticmethod
    def geom_to_h3_cell(geom, resolution: int = 9):
        centroid = func.ST_Centroid(geom)
        return func.h3_lat_lng_to_cell(
            func.point(func.ST_Y(centroid), func.ST_X(centroid)),
            resolution,
        )
