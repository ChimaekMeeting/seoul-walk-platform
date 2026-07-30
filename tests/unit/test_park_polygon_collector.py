import importlib
import sys
from unittest.mock import MagicMock

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

sys.modules.pop("src.repository.layer.nature_repository", None)
nature_repository_module = importlib.import_module(
    "src.repository.layer.nature_repository"
)
NatureRepository = nature_repository_module.NatureRepository

sys.modules.pop("src.data.collectors.park_polygon_collector", None)
ParkPolygonCollector = importlib.import_module(
    "src.data.collectors.park_polygon_collector"
).ParkPolygonCollector
WalkEdge = importlib.import_module("src.entity.network.walk_edge").WalkEdge


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


def write_boundary_shapefile(path, *, crs="EPSG:5174"):
    boundary = Polygon(
        [
            (197_900, 449_900),
            (198_250, 449_900),
            (198_250, 450_250),
            (197_900, 450_250),
        ]
    )
    gdf = gpd.GeoDataFrame(
        {"COL_ADM_SE": ["11110"]},
        geometry=[boundary],
        crs=crs,
    )
    gdf.to_file(path, encoding="cp949")


def test_build_records_preserves_source_and_repairs_geometry(tmp_path):
    raw_path = tmp_path / "parks.shp"
    boundary_path = tmp_path / "boundary.shp"
    write_park_shapefile(raw_path)
    write_boundary_shapefile(boundary_path)

    records = ParkPolygonCollector(raw_path, boundary_path).build_records()

    assert len(records) == 2
    assert records.crs.to_epsg() == 4326
    assert records.geom.is_valid.all()
    assert set(records.source_id) == {"park-1", "park-2"}
    assert set(records.name) == {"첫 번째 공원", "두 번째 공원"}
    assert set(records.green_type) == {"seoul_park_polygon"}
    assert set(records.source_name) == {"seoul_living_area_plan_park"}


def test_build_records_rejects_missing_crs(tmp_path):
    raw_path = tmp_path / "parks_without_crs.shp"
    boundary_path = tmp_path / "boundary.shp"
    write_park_shapefile(raw_path, crs=None)
    write_boundary_shapefile(boundary_path)

    with pytest.raises(ValueError, match="좌표계"):
        ParkPolygonCollector(raw_path, boundary_path).build_records()


def test_build_records_rejects_missing_required_columns(tmp_path):
    raw_path = tmp_path / "parks_without_label.shp"
    boundary_path = tmp_path / "boundary.shp"
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
    write_boundary_shapefile(boundary_path)

    with pytest.raises(ValueError, match="LABEL"):
        ParkPolygonCollector(raw_path, boundary_path).build_records()


def test_build_records_clips_geometry_to_seoul_boundary(tmp_path):
    raw_path = tmp_path / "parks.shp"
    boundary_path = tmp_path / "boundary.shp"
    write_park_shapefile(raw_path)
    write_boundary_shapefile(boundary_path)

    records = ParkPolygonCollector(raw_path, boundary_path).build_records()
    projected = records.to_crs("EPSG:5174")

    first = projected.loc[projected.source_id == "park-1", "geom"].iloc[0]
    second = projected.loc[projected.source_id == "park-2", "geom"].iloc[0]
    assert first.area == pytest.approx(10_000, rel=0.01)
    assert second.area == pytest.approx(2_500, rel=0.05)


def test_walk_edge_has_park_overlap_ratio_column():
    column = WalkEdge.__table__.c.park_overlap_ratio

    assert column.nullable is False
    assert column.server_default.arg == "0.0"


def test_update_edge_stores_overlap_ratio_without_updating_nature_score(monkeypatch):
    connection = MagicMock()
    overlap_result = MagicMock(rowcount=13)
    connection.execute.side_effect = [MagicMock(), overlap_result]
    transaction = MagicMock()
    transaction.__enter__.return_value = connection
    engine = MagicMock()
    engine.begin.return_value = transaction
    monkeypatch.setattr(nature_repository_module, "engine", engine)

    updated = NatureRepository.update_edge_park_overlap_ratios(
        "seoul_park_polygon"
    )

    statements = [str(call.args[0]) for call in connection.execute.call_args_list]
    combined_sql = "\n".join(statements)
    assert updated == 13
    assert "SET park_overlap_ratio = 0.0" in combined_sql
    assert "SET park_overlap_ratio = overlap.overlap_ratio" in combined_sql
    assert "ST_Intersection(edge.geom, nature.geom)" in combined_sql
    assert "nature_score" not in combined_sql
    assert connection.execute.call_args_list[1].args[1] == {
        "green_type": "seoul_park_polygon"
    }
