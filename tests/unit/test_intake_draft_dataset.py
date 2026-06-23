"""
tests/unit/test_intake_draft_dataset.py
draft_dataset.py(src/data/intake)의 순수 함수에 대한 최소 단위 테스트.

input()을 사용하는 대화형 흐름(collect_answers)은 여기서 다루지 않고,
파싱/조립/검증을 담당하는 순수 함수만 테스트한다.
"""

import pytest

from src.data.intake.draft_dataset import (
    RECORD_DISCLAIMER,
    build_dataset_entry,
    coalesce,
    ensure_overwrite_allowed,
    first_matching_or_none,
    first_or_none,
    parse_profiles,
    render_record_section,
    upsert_intake_record,
    validate_dataset_key,
)


# ── coalesce ─────────────────────────────────────────────────────────────────


class TestCoalesce:
    def test_빈_문자열이면_기본값을_사용한다(self):
        assert coalesce("", "default") == "default"

    def test_공백만_있으면_기본값을_사용한다(self):
        assert coalesce("   ", "default") == "default"

    def test_None이면_기본값을_사용한다(self):
        assert coalesce(None, "default") == "default"

    def test_값이_있으면_strip된_값을_사용한다(self):
        assert coalesce("  서울  ", "default") == "서울"


# ── parse_profiles ───────────────────────────────────────────────────────────


class TestParseProfiles:
    def test_comma_separated_문자열을_리스트로_변환한다(self):
        assert parse_profiles("nature, healing ,default") == ["nature", "healing", "default"]

    def test_빈_문자열이면_빈_리스트를_반환한다(self):
        assert parse_profiles("") == []

    def test_공백만_있으면_빈_리스트를_반환한다(self):
        assert parse_profiles("   ") == []

    def test_중간에_빈_토큰이_있으면_제외한다(self):
        assert parse_profiles("nature,,healing") == ["nature", "healing"]


# ── first_or_none / first_matching_or_none ──────────────────────────────────


class TestFirstOrNone:
    def test_후보가_있으면_첫번째를_반환한다(self):
        assert first_or_none(["a", "b"]) == "a"

    def test_후보가_없으면_None을_반환한다(self):
        assert first_or_none([]) is None


class TestFirstMatchingOrNone:
    def test_토큰이_포함된_첫_후보를_반환한다(self):
        candidates = ["가로수길종료위도", "가로수길시작위도"]
        assert first_matching_or_none(candidates, ["시작", "기점", "start"]) == "가로수길시작위도"

    def test_일치하는_후보가_없으면_None을_반환한다(self):
        assert first_matching_or_none(["위도"], ["시작", "기점", "start"]) is None


# ── ensure_overwrite_allowed ─────────────────────────────────────────────────


class TestEnsureOverwriteAllowed:
    def _registry(self) -> dict:
        return {"datasets": {"street_tree": {"approved": False}}}

    def test_존재하지_않는_dataset_key는_허용한다(self):
        ensure_overwrite_allowed(self._registry(), "seoul_trail", overwrite=False)

    def test_존재하는_dataset_key는_overwrite_false면_에러(self):
        with pytest.raises(ValueError):
            ensure_overwrite_allowed(self._registry(), "street_tree", overwrite=False)

    def test_존재하는_dataset_key도_overwrite_true면_허용한다(self):
        ensure_overwrite_allowed(self._registry(), "street_tree", overwrite=True)


# ── validate_dataset_key ─────────────────────────────────────────────────────


class TestValidateDatasetKey:
    def test_공백을_trim해서_반환한다(self):
        assert validate_dataset_key("  street_tree  ") == "street_tree"

    def test_빈_값이면_에러(self):
        with pytest.raises(ValueError):
            validate_dataset_key("")

    def test_None이면_에러(self):
        with pytest.raises(ValueError):
            validate_dataset_key(None)


# ── build_dataset_entry ──────────────────────────────────────────────────────


class TestBuildDatasetEntry:
    def test_configured_dataset_LINESTRING_entry를_만든다(self):
        answers = {
            "dataset_type": "configured",
            "feature": "nature",
            "score_column": "nature_score",
            "score_effect": "bonus",
            "profiles": ["nature", "healing"],
            "ai_expression": "가로수가 있는 길을 일부 반영할 수 있음",
            "geometry": "LINESTRING",
            "start_lat_col": "가로수길시작위도",
            "start_lon_col": "가로수길시작경도",
            "end_lat_col": "가로수길종료위도",
            "end_lon_col": "가로수길종료경도",
            "city_filter_col": "제공기관명",
            "city_filter_value": "서울",
            "name_col": "가로수길명",
            "address_col": None,
        }

        entry = build_dataset_entry(
            file_name="전국가로수길정보표준데이터.csv",
            source_type="csv",
            raw_table="csv_raw",
            answers=answers,
        )

        assert entry["approved"] is False
        assert entry["dataset_type"] == "configured"
        assert entry["source_type"] == "csv"
        assert entry["file"] == "전국가로수길정보표준데이터.csv"
        assert entry["raw_table"] == "csv_raw"
        assert entry["geometry"] == "LINESTRING"
        assert entry["start_lat_col"] == "가로수길시작위도"
        assert entry["end_lon_col"] == "가로수길종료경도"
        assert entry["city_filter_col"] == "제공기관명"
        assert entry["city_filter_value"] == "서울"
        assert entry["name_col"] == "가로수길명"
        assert entry["score_column"] == "nature_score"
        assert entry["score_effect"] == "bonus"
        assert entry["profiles"] == ["nature", "healing"]
        assert "lat_col" not in entry
        assert "adapter" not in entry
        assert entry["note"].startswith("draft_dataset.py로 생성된 초안입니다")

    def test_configured_dataset_POINT_entry는_lat_lon_col을_사용한다(self):
        answers = {
            "dataset_type": "configured",
            "feature": "safety",
            "score_column": "safety_score",
            "score_effect": "bonus",
            "profiles": ["default"],
            "ai_expression": "안전 시설 위치를 일부 반영할 수 있음",
            "geometry": "POINT",
            "lat_col": "위도",
            "lon_col": "경도",
            "city_filter_col": None,
            "city_filter_value": None,
            "name_col": None,
            "address_col": None,
        }

        entry = build_dataset_entry(
            file_name="dummy.csv", source_type="csv", raw_table="csv_raw", answers=answers
        )

        assert entry["lat_col"] == "위도"
        assert entry["lon_col"] == "경도"
        assert "start_lat_col" not in entry

    def test_adapter_dataset_entry를_만든다(self):
        answers = {
            "dataset_type": "adapter",
            "feature": "landmark",
            "score_column": "landmark_score",
            "score_effect": "bonus",
            "profiles": ["landmark"],
            "ai_expression": "관광지 정보를 일부 반영할 수 있음",
            "adapter": "TourApiAdapter",
            "collector": "LandmarkCollector",
            "layer": "landmark_layer",
        }

        entry = build_dataset_entry(
            file_name="none", source_type="api", raw_table="public_raw", answers=answers
        )

        assert entry["dataset_type"] == "adapter"
        assert entry["adapter"] == "TourApiAdapter"
        assert entry["collector"] == "LandmarkCollector"
        assert entry["layer"] == "landmark_layer"
        assert "geometry" not in entry
        assert "lat_col" not in entry


# ── render_record_section ─────────────────────────────────────────────────────


class TestRenderRecordSection:
    def _entry(self) -> dict:
        return {
            "approved": False,
            "dataset_type": "configured",
            "source_type": "csv",
            "file": "전국가로수길정보표준데이터.csv",
            "geometry": "LINESTRING",
            "city_filter_col": "제공기관명",
            "city_filter_value": "서울",
            "score_column": "nature_score",
            "score_effect": "bonus",
            "profiles": ["nature", "healing"],
            "ai_expression": "가로수가 있는 길을 일부 반영할 수 있음",
        }

    def _report(self) -> dict:
        return {
            "rows": 10333,
            "quality": {
                "missing_coordinates": 0,
                "invalid_coordinates": 0,
                "duplicate_coordinates": 1040,
                "seoul_bbox_outliers": 9035,
            },
        }

    def test_필수_필드를_모두_포함한다(self):
        section = render_record_section("street_tree", self._entry(), self._report())

        assert "<!-- intake-record:street_tree:start -->" in section
        assert "<!-- intake-record:street_tree:end -->" in section
        assert "## street_tree" in section
        assert "- file: 전국가로수길정보표준데이터.csv" in section
        assert "- approved: False" in section
        assert "- source_type: csv" in section
        assert "- geometry: LINESTRING" in section
        assert "- city_filter: 제공기관명 = 서울" in section
        assert "- score_column: nature_score" in section
        assert "- score_effect: bonus" in section
        assert "- profiles: nature, healing" in section
        assert "- ai_expression: 가로수가 있는 길을 일부 반영할 수 있음" in section
        assert "- rows: 10333" in section
        assert "- duplicate_coordinates: 1040" in section
        assert "- seoul_bbox_outliers: 9035" in section
        assert RECORD_DISCLAIMER in section

    def test_city_filter가_없으면_none으로_표시한다(self):
        entry = self._entry()
        entry["city_filter_col"] = None
        section = render_record_section("street_tree", entry, self._report())
        assert "- city_filter: none" in section

    def test_quality가_없으면_rows만_포함하고_에러내지_않는다(self):
        section = render_record_section("street_tree", self._entry(), {"rows": 10333, "quality": None})
        assert "- rows: 10333" in section
        assert "missing_coordinates" not in section


# ── upsert_intake_record ──────────────────────────────────────────────────────


class TestUpsertIntakeRecord:
    def test_파일이_없으면_새로_만들고_섹션을_추가한다(self, tmp_path):
        doc_path = tmp_path / "data_intake_records.md"
        section = "<!-- intake-record:street_tree:start -->\n## street_tree\n<!-- intake-record:street_tree:end -->"

        status = upsert_intake_record(doc_path, "street_tree", section, overwrite=False)

        assert status == "appended"
        text = doc_path.read_text(encoding="utf-8")
        assert RECORD_DISCLAIMER in text
        assert "## street_tree" in text

    def test_같은_dataset_key가_있으면_기본적으로_건너뛴다(self, tmp_path):
        doc_path = tmp_path / "data_intake_records.md"
        section = "<!-- intake-record:street_tree:start -->\n## street_tree\noriginal\n<!-- intake-record:street_tree:end -->"
        upsert_intake_record(doc_path, "street_tree", section, overwrite=False)

        status = upsert_intake_record(doc_path, "street_tree", section.replace("original", "changed"), overwrite=False)

        assert status == "skipped"
        text = doc_path.read_text(encoding="utf-8")
        assert "original" in text
        assert "changed" not in text

    def test_overwrite_true면_섹션을_갱신한다(self, tmp_path):
        doc_path = tmp_path / "data_intake_records.md"
        section = "<!-- intake-record:street_tree:start -->\n## street_tree\noriginal\n<!-- intake-record:street_tree:end -->"
        upsert_intake_record(doc_path, "street_tree", section, overwrite=False)

        status = upsert_intake_record(doc_path, "street_tree", section.replace("original", "changed"), overwrite=True)

        assert status == "updated"
        text = doc_path.read_text(encoding="utf-8")
        assert "changed" in text
        assert "original" not in text

    def test_다른_dataset_key_섹션은_그대로_유지된다(self, tmp_path):
        doc_path = tmp_path / "data_intake_records.md"
        section_a = "<!-- intake-record:street_tree:start -->\n## street_tree\n<!-- intake-record:street_tree:end -->"
        section_b = "<!-- intake-record:seoul_trail:start -->\n## seoul_trail\n<!-- intake-record:seoul_trail:end -->"

        upsert_intake_record(doc_path, "street_tree", section_a, overwrite=False)
        upsert_intake_record(doc_path, "seoul_trail", section_b, overwrite=False)

        text = doc_path.read_text(encoding="utf-8")
        assert "## street_tree" in text
        assert "## seoul_trail" in text
