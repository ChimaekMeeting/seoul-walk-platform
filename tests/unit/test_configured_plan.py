"""
tests/unit/test_configured_plan.py
src/data/configured/plan.py의 raw/layer/score/profile 반영 계획 조립 함수에
대한 단위 테스트.

DB는 전혀 사용하지 않고, registry dict와 임시 파일만으로 build_plan을
end-to-end로 테스트한다.
"""

from pathlib import Path

import pytest

from src.data.configured.plan import (
    build_decision_items,
    build_layer_plan,
    build_plan,
    build_profile_plan,
    build_schema_warnings,
    build_score_plan,
)


# ── build_layer_plan: target_layer 추정 ───────────────────────────────────────


class TestBuildLayerPlan:
    @pytest.mark.parametrize(
        "score_column,expected_layer",
        [
            ("nature_score", "nature_layer"),
            ("safety_score", "safety_layer"),
            ("running_score", "running_layer"),
            ("child_score", "child_layer"),
            ("landmark_score", "landmark_layer"),
            ("undecided", "undecided"),
            (None, "undecided"),
        ],
    )
    def test_score_column으로_target_layer를_추정한다(self, score_column, expected_layer):
        layer_plan = build_layer_plan({"score_column": score_column})
        assert layer_plan["target_layer"] == expected_layer

    def test_csv_raw에서_nature_layer로_가면_schema_불일치_warning이다(self):
        layer_plan = build_layer_plan({"score_column": "nature_score"})
        assert layer_plan["compatibility"] == "warning"
        assert layer_plan["layer_current_source_ref"] == "osm_raw_id"

    def test_safety_layer는_csv_raw_id를_이미_가지고_있어_ok다(self):
        layer_plan = build_layer_plan({"score_column": "safety_score"})
        assert layer_plan["compatibility"] == "ok"


# ── build_schema_warnings ──────────────────────────────────────────────────────


class TestBuildSchemaWarnings:
    def test_street_tree가_nature_layer로_가면_경고를_만든다(self):
        layer_plan = build_layer_plan({"score_column": "nature_score"})
        warnings = build_schema_warnings("street_tree", layer_plan)

        assert warnings, "schema 불일치 경고가 있어야 한다"
        joined = " ".join(warnings)
        assert "nature_layer" in joined
        assert "csv_raw_id" in joined
        assert "street_tree_layer" in joined

    def test_compatibility가_ok면_경고가_없다(self):
        layer_plan = build_layer_plan({"score_column": "safety_score"})
        warnings = build_schema_warnings("streetlight", layer_plan)
        assert warnings == []


# ── build_score_plan: LINESTRING centroid 경고 ────────────────────────────────


class TestBuildScorePlan:
    def test_nature_score와_LINESTRING이면_centroid_경고를_포함한다(self):
        score_plan = build_score_plan({"score_column": "nature_score", "score_effect": "bonus"}, "LINESTRING")
        joined = " ".join(score_plan["warnings"])
        assert "centroid" in joined or "중심점" in joined
        assert "NatureRepository.get_nature_h3_counts" in joined

    def test_POINT이면_centroid_경고가_없다(self):
        score_plan = build_score_plan({"score_column": "safety_score", "score_effect": "bonus"}, "POINT")
        assert score_plan["warnings"] == []


# ── build_profile_plan ────────────────────────────────────────────────────────


class TestBuildProfilePlan:
    def test_healing_layer_score를_자동_생성하지_않는다고_명시한다(self):
        profile_plan = build_profile_plan({"profiles": ["nature", "healing"]})
        assert "healing_layer" in profile_plan["note"]
        assert "healing_score" in profile_plan["note"]
        assert "자동 생성하지 않는다" in profile_plan["note"]

    def test_profile_존재여부_확인이_필요하다는_warning을_포함한다(self):
        profile_plan = build_profile_plan({"profiles": ["nature", "healing"]})
        assert "별도 확인" in profile_plan["warning"]


# ── build_decision_items ───────────────────────────────────────────────────────


class TestBuildDecisionItems:
    def test_schema_경고와_LINESTRING이_있으면_4개_결정항목을_만든다(self):
        layer_plan = build_layer_plan({"score_column": "nature_score"})
        items = build_decision_items("street_tree", layer_plan, "LINESTRING")
        assert len(items) == 4
        assert any("csv_raw_id" in item for item in items)
        assert any("street_tree_layer" in item for item in items)
        assert any("centroid" in item for item in items)


# ── build_plan: end-to-end, DB 없이 순수 데이터 구조 ───────────────────────────


class TestBuildPlan:
    def _write_csv(self, tmp_path) -> Path:
        raw_dir = tmp_path / "raw"
        raw_dir.mkdir()
        csv_path = raw_dir / "전국가로수길정보표준데이터.csv"
        csv_path.write_text(
            "가로수길명,가로수길시작위도,가로수길시작경도,가로수길종료위도,가로수길종료경도,제공기관명\n"
            "서울길,37.5,127.0,37.51,127.01,서울특별시\n"
            "지방길,36.0,128.0,36.01,128.01,부산광역시\n",
            encoding="utf-8",
        )
        return raw_dir

    def _registry_path(self, tmp_path) -> Path:
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
            "    profiles: [nature, healing]\n"
            "    ai_expression: 가로수가 있는 길을 일부 반영할 수 있음\n",
            encoding="utf-8",
        )
        return registry_path

    def test_plan은_순수_데이터_구조이며_DB를_사용하지_않는다(self, tmp_path):
        raw_dir = self._write_csv(tmp_path)
        registry_path = self._registry_path(tmp_path)

        plan = build_plan("street_tree", registry_path=registry_path, raw_dir=raw_dir)

        assert isinstance(plan, dict)
        assert plan["dataset_key"] == "street_tree"
        assert plan["geometry_type"] == "LINESTRING"
        assert plan["layer_plan"]["target_layer"] == "nature_layer"
        assert plan["layer_plan"]["compatibility"] == "warning"
        assert plan["schema_warnings"], "street_tree -> nature_layer는 schema 경고가 있어야 한다"
        assert any("centroid" in w or "중심점" in w for w in plan["score_plan"]["warnings"])
        assert "healing_layer" in plan["profile_plan"]["note"]
        assert len(plan["decision_items"]) == 4

    def test_dataset_key가_없으면_에러(self, tmp_path):
        raw_dir = self._write_csv(tmp_path)
        registry_path = self._registry_path(tmp_path)
        with pytest.raises(ValueError):
            build_plan("no_such_key", registry_path=registry_path, raw_dir=raw_dir)
