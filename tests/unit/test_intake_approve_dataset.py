"""
tests/unit/test_intake_approve_dataset.py
approve_dataset.py(src/data/intake)의 순수 함수에 대한 최소 단위 테스트.

CLI(main/parse_args)는 다루지 않고, registry entry 승격/docs 결정 기록 조립을
담당하는 순수 함수만 테스트한다.
"""

import pytest

from src.data.intake.approve_dataset import (
    AlreadyApprovedError,
    DatasetNotFoundError,
    approve_dataset_entry,
    get_dataset_or_raise,
    render_decision_block,
    upsert_decision_record,
)
from src.data.intake.draft_dataset import RECORD_DISCLAIMER


# ── get_dataset_or_raise ───────────────────────────────────────────────────────


class TestGetDatasetOrRaise:
    def test_존재하는_dataset_key를_반환한다(self):
        registry = {"datasets": {"street_tree": {"approved": False}}}
        entry = get_dataset_or_raise(registry, "street_tree")
        assert entry == {"approved": False}

    def test_존재하지_않으면_DatasetNotFoundError(self):
        registry = {"datasets": {}}
        with pytest.raises(DatasetNotFoundError):
            get_dataset_or_raise(registry, "street_tree")

    def test_datasets가_없는_registry도_안전하게_처리한다(self):
        with pytest.raises(DatasetNotFoundError):
            get_dataset_or_raise({}, "street_tree")


# ── approve_dataset_entry ──────────────────────────────────────────────────────


class TestApproveDatasetEntry:
    def _draft_entry(self) -> dict:
        return {
            "approved": False,
            "dataset_type": "configured",
            "file": "전국가로수길정보표준데이터.csv",
            "score_column": "nature_score",
            "profiles": ["nature", "healing"],
        }

    def test_approved_true와_메타데이터를_채운다(self):
        updated = approve_dataset_entry(
            self._draft_entry(),
            decision="nature_score로 반영",
            reason="자연친화 근거로 사용 가능",
            approved_at="2026-06-23",
        )

        assert updated["approved"] is True
        assert updated["approved_at"] == "2026-06-23"
        assert updated["decision"] == "nature_score로 반영"
        assert updated["reason"] == "자연친화 근거로 사용 가능"
        # 기존 필드는 그대로 유지된다.
        assert updated["file"] == "전국가로수길정보표준데이터.csv"
        assert updated["profiles"] == ["nature", "healing"]

    def test_원본_entry는_변경하지_않는다(self):
        original = self._draft_entry()
        approve_dataset_entry(
            original, decision="d", reason="r", approved_at="2026-06-23"
        )
        assert original["approved"] is False
        assert "approved_at" not in original

    def test_이미_approved_true면_기본적으로_에러(self):
        entry = self._draft_entry()
        entry["approved"] = True
        with pytest.raises(AlreadyApprovedError):
            approve_dataset_entry(entry, decision="d", reason="r", approved_at="2026-06-23")

    def test_force면_이미_approved_true여도_갱신한다(self):
        entry = self._draft_entry()
        entry["approved"] = True
        updated = approve_dataset_entry(
            entry, decision="갱신", reason="재검토", approved_at="2026-06-24", force=True
        )
        assert updated["approved"] is True
        assert updated["decision"] == "갱신"
        assert updated["approved_at"] == "2026-06-24"


# ── render_decision_block ──────────────────────────────────────────────────────


class TestRenderDecisionBlock:
    def test_decision_reason_approved_at을_포함한다(self):
        block = render_decision_block(
            decision="nature_score로 반영", reason="자연친화 근거", approved_at="2026-06-23"
        )
        assert "2026-06-23" in block
        assert "nature_score로 반영" in block
        assert "자연친화 근거" in block
        assert "approved: true" in block


# ── upsert_decision_record ─────────────────────────────────────────────────────


class TestUpsertDecisionRecord:
    def _entry(self) -> dict:
        return {
            "approved": True,
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

    def test_기존_섹션이_있으면_그_안에_결정_기록을_추가한다(self, tmp_path):
        doc_path = tmp_path / "data_intake_records.md"
        doc_path.write_text(
            "# 데이터 intake 기록\n\n"
            "<!-- intake-record:street_tree:start -->\n"
            "## street_tree\n"
            "- file: 전국가로수길정보표준데이터.csv\n"
            "<!-- intake-record:street_tree:end -->\n",
            encoding="utf-8",
        )
        decision_block = render_decision_block(
            decision="nature_score로 반영", reason="자연친화 근거", approved_at="2026-06-23"
        )

        status = upsert_decision_record(doc_path, "street_tree", self._entry(), decision_block)

        assert status == "appended_to_existing"
        text = doc_path.read_text(encoding="utf-8")
        assert "- file: 전국가로수길정보표준데이터.csv" in text
        assert "### 승인 기록 (2026-06-23)" in text
        assert "nature_score로 반영" in text
        # 결정 기록은 end marker 앞에, 기존 내용은 보존된 채로 들어간다.
        assert text.index("### 승인 기록") < text.index("<!-- intake-record:street_tree:end -->")

    def test_섹션이_없으면_registry_entry로_최소_섹션을_만들고_결정을_덧붙인다(self, tmp_path):
        doc_path = tmp_path / "data_intake_records.md"
        decision_block = render_decision_block(
            decision="nature_score로 반영", reason="자연친화 근거", approved_at="2026-06-23"
        )

        status = upsert_decision_record(doc_path, "street_tree", self._entry(), decision_block)

        assert status == "created_with_decision"
        text = doc_path.read_text(encoding="utf-8")
        assert "## street_tree" in text
        assert "- score_column: nature_score" in text
        assert "### 승인 기록 (2026-06-23)" in text
        assert RECORD_DISCLAIMER in text

    def test_파일이_없으면_새로_만든다(self, tmp_path):
        doc_path = tmp_path / "data_intake_records.md"
        decision_block = render_decision_block(decision="d", reason="r", approved_at="2026-06-23")

        upsert_decision_record(doc_path, "street_tree", self._entry(), decision_block)

        assert doc_path.exists()
        assert RECORD_DISCLAIMER in doc_path.read_text(encoding="utf-8")

    def test_다른_dataset_key_섹션은_건드리지_않는다(self, tmp_path):
        doc_path = tmp_path / "data_intake_records.md"
        doc_path.write_text(
            "# 데이터 intake 기록\n\n"
            "<!-- intake-record:seoul_trail:start -->\n"
            "## seoul_trail\n"
            "<!-- intake-record:seoul_trail:end -->\n",
            encoding="utf-8",
        )
        decision_block = render_decision_block(decision="d", reason="r", approved_at="2026-06-23")

        upsert_decision_record(doc_path, "street_tree", self._entry(), decision_block)

        text = doc_path.read_text(encoding="utf-8")
        assert "## seoul_trail" in text
        assert "## street_tree" in text
