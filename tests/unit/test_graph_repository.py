import importlib
import sys
from types import SimpleNamespace


sys.modules.pop("src.repository.network.graph_repository", None)
GraphRepository = importlib.import_module(
    "src.repository.network.graph_repository"
).GraphRepository


def make_edge_row(**overrides):
    values = {
        "link_id": 100,
        "length_m": 25.5,
        "raw_link_type_code": "1010",
        "is_walkable": True,
        "raw_is_tunnel": False,
        "raw_is_bridge": False,
        "raw_is_overpass": False,
        "raw_is_crosswalk": False,
        "raw_is_elevated": False,
        "raw_is_subway_network": False,
        "raw_is_park_green": False,
        "raw_is_building_inside": False,
        "safety_score": 0.7,
        "nature_score": 0.6,
        "slope_score": 0.5,
        "running_score": 0.4,
        "landmark_score": 0.3,
        "child_score": 0.2,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_edge_attributes_preserve_raw_fields_and_create_tags():
    row = make_edge_row(
        raw_is_tunnel=True,
        raw_is_bridge=True,
        raw_is_park_green=True,
    )

    attributes = GraphRepository._edge_attributes(row)

    assert attributes is not None
    assert attributes["raw_link_type_code"] == "1010"
    assert attributes["is_walkable"] is True
    assert attributes["raw_is_tunnel"] is True
    assert attributes["raw_is_bridge"] is True
    assert attributes["raw_is_park_green"] is True
    assert attributes["tags"] == ["tunnel", "bridge", "park_green"]
    assert "underground" not in attributes["tags"]


def test_edge_attributes_keep_scores():
    attributes = GraphRepository._edge_attributes(make_edge_row())

    assert attributes is not None
    assert attributes["length"] == 25.5
    assert attributes["safety_score"] == 0.7
    assert attributes["nature_score"] == 0.6
    assert attributes["slope_score"] == 0.5
    assert attributes["running_score"] == 0.4
    assert attributes["landmark_score"] == 0.3
    assert attributes["child_score"] == 0.2


def test_edge_attributes_exclude_non_walkable_link():
    row = make_edge_row(is_walkable=False)

    assert GraphRepository._edge_attributes(row) is None
