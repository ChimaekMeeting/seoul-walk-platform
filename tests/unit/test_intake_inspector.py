"""
tests/unit/test_intake_inspector.py
intake inspector(src/data/intake)의 후보 탐지/조회 함수에 대한 최소 단위 테스트.
"""

import pandas as pd

from src.data.intake.inspect_dataset import (
    detect_lat_lon_candidates,
    estimate_geometry_candidate,
)
from src.data.intake.registry import find_dataset_by_file


# ── 좌표 후보 탐지 ────────────────────────────────────────────────────────────


class TestDetectLatLonCandidates:
    def test_표준_위도_경도_컬럼을_탐지한다(self):
        lat, lon = detect_lat_lon_candidates(["위도", "경도", "명칭"])
        assert lat == ["위도"]
        assert lon == ["경도"]

    def test_접두사가_붙은_위도_경도_컬럼도_탐지한다(self):
        """전국가로수길정보표준데이터.csv 실제 컬럼 패턴(가로수길시작위도 등)."""
        columns = ["가로수길시작위도", "가로수길시작경도", "가로수길종료위도", "가로수길종료경도"]
        lat, lon = detect_lat_lon_candidates(columns)
        assert lat == ["가로수길시작위도", "가로수길종료위도"]
        assert lon == ["가로수길시작경도", "가로수길종료경도"]

    def test_wgs84_좌표_컬럼을_탐지한다(self):
        lat, lon = detect_lat_lon_candidates(["WGS84위도", "WGS84경도", "Y좌표(WGS84)", "X좌표(WGS84)"])
        assert lat == ["WGS84위도", "Y좌표(WGS84)"]
        assert lon == ["WGS84경도", "X좌표(WGS84)"]

    def test_관련_없는_컬럼은_후보에_포함되지_않는다(self):
        lat, lon = detect_lat_lon_candidates(["이름", "주소", "전화번호"])
        assert lat == []
        assert lon == []


# ── geometry 후보 추정 ──────────────────────────────────────────────────────


class TestEstimateGeometryCandidate:
    def test_위경도만_있으면_POINT다(self):
        result = estimate_geometry_candidate(
            columns=["위도", "경도"],
            lat_candidates=["위도"],
            lon_candidates=["경도"],
        )
        assert result == "POINT"

    def test_기점_종점_패턴이_있으면_LINESTRING이다(self):
        result = estimate_geometry_candidate(
            columns=["기점위도", "기점경도", "종점위도", "종점경도"],
            lat_candidates=["기점위도", "종점위도"],
            lon_candidates=["기점경도", "종점경도"],
        )
        assert result == "LINESTRING"

    def test_geometry_컬럼이_있으면_WKT_GEOMETRY다(self):
        result = estimate_geometry_candidate(
            columns=["geometry", "name"],
            lat_candidates=[],
            lon_candidates=[],
        )
        assert result == "WKT/GEOMETRY"

    def test_좌표_후보가_없으면_unknown이다(self):
        result = estimate_geometry_candidate(
            columns=["이름", "주소"],
            lat_candidates=[],
            lon_candidates=[],
        )
        assert result == "unknown"


# ── registry 조회 ────────────────────────────────────────────────────────────


class TestFindDatasetByFile:
    def _registry(self) -> dict:
        return {
            "datasets": {
                "street_tree": {
                    "file": "전국가로수길정보표준데이터.csv",
                    "approved": False,
                    "layer": "undecided",
                },
                "streetlight": {
                    "file": "전국스마트가로등표준데이터.csv",
                    "approved": True,
                    "layer": "safety_layer",
                },
            }
        }

    def test_파일명이_일치하면_dataset_key와_값을_반환한다(self):
        key, dataset = find_dataset_by_file(self._registry(), "전국가로수길정보표준데이터.csv")
        assert key == "street_tree"
        assert dataset["approved"] is False

    def test_파일명이_일치하지_않으면_None을_반환한다(self):
        key, dataset = find_dataset_by_file(self._registry(), "존재하지않는파일.csv")
        assert key is None
        assert dataset is None

    def test_datasets가_없는_registry도_안전하게_처리한다(self):
        key, dataset = find_dataset_by_file({}, "anything.csv")
        assert key is None
        assert dataset is None
