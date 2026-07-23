import importlib
import sys
from unittest.mock import MagicMock

import pytest


for prefix in ("geopandas", "shapely", "pyproj"):
    for module_name in list(sys.modules):
        if module_name == prefix or module_name.startswith(f"{prefix}."):
            sys.modules.pop(module_name, None)

gpd = importlib.import_module("geopandas")
Polygon = importlib.import_module("shapely.geometry").Polygon

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
