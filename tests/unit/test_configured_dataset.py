"""
tests/unit/test_configured_dataset.py
src/data/configured/configured_dataset.py의 registry 검증/필터/정제/record 생성
함수에 대한 단위 테스트.

DB는 전혀 사용하지 않고, pandas DataFrame과 registry dict만으로 테스트한다.
"""

import pandas as pd
import pytest

from src.data.configured.configured_dataset import (
    DatasetNotApprovedError,
    DatasetNotFoundError,
    UnsupportedDatasetTypeError,
    UnsupportedGeometryError,
    UnsupportedSourceTypeError,
    apply_city_filter,
    build_records,
    clean_coordinates,
    get_approved_configured_dataset,
    load_configured_dataset,
)


# ── get_approved_configured_dataset ──────────────────────────────────────────


class TestGetApprovedConfiguredDataset:
    def _entry(self, **overrides) -> dict:
        base = {
            "approved": True,
            "dataset_type": "configured",
            "source_type": "csv",
            "file": "dummy.csv",
        }
        base.update(overrides)
        return base

    def test_approved_configured_csv는_그대로_반환한다(self):
        registry = {"datasets": {"street_tree": self._entry()}}
        entry = get_approved_configured_dataset(registry, "street_tree")
        assert entry["file"] == "dummy.csv"

    def test_dataset_key가_없으면_에러(self):
        registry = {"datasets": {}}
        with pytest.raises(DatasetNotFoundError):
            get_approved_configured_dataset(registry, "street_tree")

    def test_approved_false면_에러(self):
        registry = {"datasets": {"street_tree": self._entry(approved=False)}}
        with pytest.raises(DatasetNotApprovedError):
            get_approved_configured_dataset(registry, "street_tree")

    def test_dataset_type_adapter면_에러(self):
        registry = {"datasets": {"street_tree": self._entry(dataset_type="adapter")}}
        with pytest.raises(UnsupportedDatasetTypeError):
            get_approved_configured_dataset(registry, "street_tree")

    def test_source_type_api면_에러(self):
        registry = {"datasets": {"street_tree": self._entry(source_type="api")}}
        with pytest.raises(UnsupportedSourceTypeError):
            get_approved_configured_dataset(registry, "street_tree")

    def test_source_type_xlsx는_허용한다(self):
        registry = {"datasets": {"cctv": self._entry(source_type="xlsx")}}
        entry = get_approved_configured_dataset(registry, "cctv")
        assert entry["source_type"] == "xlsx"


# ── apply_city_filter ─────────────────────────────────────────────────────────


class TestApplyCityFilter:
    def _df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "제공기관명": ["서울특별시", "부산광역시", "서울특별시 강남구"],
                "name": ["a", "b", "c"],
            }
        )

    def test_contains_필터를_적용한다(self):
        entry = {"city_filter_col": "제공기관명", "city_filter_value": "서울"}
        result = apply_city_filter(self._df(), entry)
        assert list(result["name"]) == ["a", "c"]

    def test_city_filter_col이_없으면_그대로_반환한다(self):
        result = apply_city_filter(self._df(), {})
        assert len(result) == 3

    def test_등록된_컬럼이_파일에_없으면_에러(self):
        entry = {"city_filter_col": "없는컬럼", "city_filter_value": "서울"}
        with pytest.raises(ValueError):
            apply_city_filter(self._df(), entry)


# ── clean_coordinates ─────────────────────────────────────────────────────────


class TestCleanCoordinatesPoint:
    def _df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "lat": [37.5, None, 37.55, 91.0],
                "lon": [127.0, 127.1, 35.0, 127.0],
            }
        )

    def test_결측_invalid_좌표를_제거한다(self):
        entry = {"geometry": "POINT", "lat_col": "lat", "lon_col": "lon"}
        result = clean_coordinates(self._df(), entry, drop_seoul_outliers=False)
        # None(결측), lat=91.0(범위 밖)인 행이 제거된다.
        assert len(result) == 2

    def test_서울_bbox_밖_좌표도_제거한다(self):
        entry = {"geometry": "POINT", "lat_col": "lat", "lon_col": "lon"}
        result = clean_coordinates(self._df(), entry, drop_seoul_outliers=True)
        # lat=37.55, lon=35.0은 결측/invalid는 아니지만 서울 밖이라 제거된다.
        assert len(result) == 1
        assert result.iloc[0]["lon"] == 127.0

    def test_등록된_컬럼이_파일에_없으면_에러(self):
        entry = {"geometry": "POINT", "lat_col": "없음", "lon_col": "lon"}
        with pytest.raises(ValueError):
            clean_coordinates(self._df(), entry)


class TestCleanCoordinatesLinestring:
    def _df(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "slat": [37.5, None],
                "slon": [127.0, 127.1],
                "elat": [37.51, 37.52],
                "elon": [127.01, 127.02],
            }
        )

    def test_시작_종료_좌표중_결측이_있으면_제거한다(self):
        entry = {
            "geometry": "LINESTRING",
            "start_lat_col": "slat",
            "start_lon_col": "slon",
            "end_lat_col": "elat",
            "end_lon_col": "elon",
        }
        result = clean_coordinates(self._df(), entry, drop_seoul_outliers=False)
        assert len(result) == 1


class TestCleanCoordinatesUnsupportedGeometry:
    def test_지원하지_않는_geometry는_에러(self):
        df = pd.DataFrame({"lat": [37.5], "lon": [127.0]})
        with pytest.raises(UnsupportedGeometryError):
            clean_coordinates(df, {"geometry": "POLYGON"})


# ── build_records ──────────────────────────────────────────────────────────────


class TestBuildRecordsPoint:
    def test_POINT_record를_만든다(self):
        df = pd.DataFrame({"lat": [37.5], "lon": [127.0], "name": ["가로등1"]})
        entry = {
            "geometry": "POINT",
            "lat_col": "lat",
            "lon_col": "lon",
            "name_col": "name",
            "feature": "safety",
            "score_column": "safety_score",
            "score_effect": "bonus",
            "ai_expression": "표현",
        }
        records = build_records(df, entry, "streetlight")

        assert len(records) == 1
        record = records[0]
        assert record["dataset_key"] == "streetlight"
        assert record["name"] == "가로등1"
        assert record["geometry_type"] == "POINT"
        assert record["wkt"] == "POINT(127.0 37.5)"
        assert record["properties"] == {
            "feature": "safety",
            "score_column": "safety_score",
            "score_effect": "bonus",
            "ai_expression": "표현",
        }

    def test_name_col이_없으면_name은_None(self):
        df = pd.DataFrame({"lat": [37.5], "lon": [127.0]})
        entry = {"geometry": "POINT", "lat_col": "lat", "lon_col": "lon"}
        records = build_records(df, entry, "streetlight")
        assert records[0]["name"] is None


class TestBuildRecordsLinestring:
    def test_LINESTRING_record를_만든다(self):
        df = pd.DataFrame(
            {
                "slat": [37.5],
                "slon": [127.0],
                "elat": [37.51],
                "elon": [127.01],
                "name": ["가로수길1"],
            }
        )
        entry = {
            "geometry": "LINESTRING",
            "start_lat_col": "slat",
            "start_lon_col": "slon",
            "end_lat_col": "elat",
            "end_lon_col": "elon",
            "name_col": "name",
            "feature": "nature",
            "score_column": "nature_score",
            "score_effect": "bonus",
            "ai_expression": "표현",
        }
        records = build_records(df, entry, "street_tree")

        assert len(records) == 1
        record = records[0]
        assert record["geometry_type"] == "LINESTRING"
        assert record["wkt"] == "LINESTRING(127.0 37.5, 127.01 37.51)"
        assert record["name"] == "가로수길1"


# ── load_configured_dataset (end-to-end, DB 없이 파일 IO만) ───────────────────


class TestLoadConfiguredDataset:
    def _write_csv(self, tmp_path) -> None:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        csv_path = raw_dir / "전국가로수길정보표준데이터.csv"
        csv_path.write_text(
            "가로수길명,가로수길시작위도,가로수길시작경도,가로수길종료위도,가로수길종료경도,제공기관명\n"
            "서울길,37.5,127.0,37.51,127.01,서울특별시\n"
            "지방길,36.0,128.0,36.01,128.01,부산광역시\n"
            "결측길,,127.0,37.51,127.01,서울특별시\n",
            encoding="utf-8",
        )
        return raw_dir

    def _registry_path(self, tmp_path) -> "Path":
        from pathlib import Path

        registry_path = tmp_path / "registry.yaml"
        registry_path.write_text(
            "version: 1\n"
            "datasets:\n"
            "  street_tree:\n"
            "    approved: true\n"
            "    dataset_type: configured\n"
            "    source_type: csv\n"
            "    file: 전국가로수길정보표준데이터.csv\n"
            "    geometry: LINESTRING\n"
            "    start_lat_col: 가로수길시작위도\n"
            "    start_lon_col: 가로수길시작경도\n"
            "    end_lat_col: 가로수길종료위도\n"
            "    end_lon_col: 가로수길종료경도\n"
            "    city_filter_col: 제공기관명\n"
            "    city_filter_value: 서울\n"
            "    name_col: 가로수길명\n"
            "    feature: nature\n"
            "    score_column: nature_score\n"
            "    score_effect: bonus\n"
            "    ai_expression: 가로수가 있는 길을 일부 반영할 수 있음\n",
            encoding="utf-8",
        )
        return registry_path

    def test_city_filter와_좌표_정제를_거쳐_record를_만든다(self, tmp_path):
        raw_dir = self._write_csv(tmp_path)
        registry_path = self._registry_path(tmp_path)

        result = load_configured_dataset(
            "street_tree", registry_path=registry_path, raw_dir=raw_dir
        )

        assert result["dataset_key"] == "street_tree"
        assert result["original_rows"] == 3
        # 부산 행이 서울 필터로 제거된다.
        assert result["after_city_filter_rows"] == 2
        # 결측 좌표 행이 좌표 정제로 제거된다.
        assert result["after_coordinate_cleanup_rows"] == 1
        assert result["geometry_type"] == "LINESTRING"
        assert len(result["records"]) == 1
        assert result["records"][0]["name"] == "서울길"

    def test_dataset_key가_없으면_에러(self, tmp_path):
        raw_dir = self._write_csv(tmp_path)
        registry_path = self._registry_path(tmp_path)
        with pytest.raises(DatasetNotFoundError):
            load_configured_dataset(
                "no_such_key", registry_path=registry_path, raw_dir=raw_dir
            )

    def test_파일이_없으면_FileNotFoundError(self, tmp_path):
        registry_path = self._registry_path(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_configured_dataset(
                "street_tree", registry_path=registry_path, raw_dir=tmp_path / "missing"
            )
