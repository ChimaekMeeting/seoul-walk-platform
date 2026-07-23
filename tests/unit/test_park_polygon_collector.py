import importlib
import sys

import pytest


for prefix in ("geopandas", "shapely", "pyproj"):
    for module_name in list(sys.modules):
        if module_name == prefix or module_name.startswith(f"{prefix}."):
            sys.modules.pop(module_name, None)

gpd = importlib.import_module("geopandas")
Polygon = importlib.import_module("shapely.geometry").Polygon

sys.modules.pop("src.data.collectors.park_polygon_collector", None)
ParkPolygonCollector = importlib.import_module(
    "src.data.collectors.park_polygon_collector"
).ParkPolygonCollector


def write_park_shapefile(path, *, crs="EPSG:5174"):
    valid = Polygon(
        [
            (198_000, 450_000),
            (198_100, 450_000),
            (198_100, 450_100),
            (198_000, 450_100),
        ]
    )
    invalid = Polygon(
        [
            (198_200, 450_000),
            (198_300, 450_100),
            (198_300, 450_000),
            (198_200, 450_100),
        ]
    )
    gdf = gpd.GeoDataFrame(
        {
            "ID": ["park-1", "park-2"],
            "LABEL": ["첫 번째 공원", "두 번째 공원"],
        },
        geometry=[valid, invalid],
        crs=crs,
    )
    gdf.to_file(path, encoding="cp949")


def test_build_records_preserves_source_and_repairs_geometry(tmp_path):
    raw_path = tmp_path / "parks.shp"
    write_park_shapefile(raw_path)

    records = ParkPolygonCollector(raw_path).build_records()

    assert len(records) == 2
    assert records.crs.to_epsg() == 4326
    assert records.geom.is_valid.all()
    assert set(records.source_id) == {"park-1", "park-2"}
    assert set(records.name) == {"첫 번째 공원", "두 번째 공원"}
    assert set(records.green_type) == {"seoul_park_polygon"}
    assert set(records.source_name) == {"seoul_living_area_plan_park"}


def test_build_records_rejects_missing_crs(tmp_path):
    raw_path = tmp_path / "parks_without_crs.shp"
    write_park_shapefile(raw_path, crs=None)

    with pytest.raises(ValueError, match="좌표계"):
        ParkPolygonCollector(raw_path).build_records()


def test_build_records_rejects_missing_required_columns(tmp_path):
    raw_path = tmp_path / "parks_without_label.shp"
    gdf = gpd.GeoDataFrame(
        {"ID": ["park-1"]},
        geometry=[
            Polygon(
                [
                    (198_000, 450_000),
                    (198_100, 450_000),
                    (198_100, 450_100),
                    (198_000, 450_100),
                ]
            )
        ],
        crs="EPSG:5174",
    )
    gdf.to_file(raw_path, encoding="cp949")

    with pytest.raises(ValueError, match="LABEL"):
        ParkPolygonCollector(raw_path).build_records()
