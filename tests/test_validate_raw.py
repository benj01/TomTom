"""Tests for validate_raw.py — filename parsing, validation, dedup, orphan detection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from validate_raw import parse_filename, validate_structure, validate_raw, file_hash, main
from tests.conftest import write_json_file, STANDARD_NODE_FORMAT, _make_node, SAMPLE_COORDS_A, SAMPLE_COORDS_B


def _good_doc(trips: int = 100) -> dict:
    """Return a minimal valid TomTom doc."""
    return {
        "nodeFormat": list(STANDARD_NODE_FORMAT),
        "nodes": [_make_node(0, None, trips, 3, SAMPLE_COORDS_A)],
    }


def _write_raw(raw_dir: Path, name: str, doc: dict | None = None) -> Path:
    """Write a valid doc with the given filename into raw_dir."""
    return write_json_file(raw_dir / name, doc or _good_doc())


# ─── Unit tests: parse_filename ─────────────────────────────────────


class TestParseFilename:
    def test_standard(self):
        parts = parse_filename("6697482674509011034_incoming_0_0.json")
        assert parts == {
            "device": "6697482674509011034",
            "direction": "incoming",
            "x": "0",
            "y": "0",
        }

    def test_outgoing(self):
        parts = parse_filename("123_outgoing_5_12.json")
        assert parts["direction"] == "outgoing"
        assert parts["x"] == "5"
        assert parts["y"] == "12"

    def test_case_insensitive(self):
        parts = parse_filename("123_INCOMING_0_0.json")
        assert parts is not None
        assert parts["direction"] == "incoming"

    def test_no_match_missing_direction(self):
        assert parse_filename("123_data_0_0.json") is None

    def test_no_match_bad_extension(self):
        assert parse_filename("123_incoming_0_0.csv") is None

    def test_no_match_non_numeric_device(self):
        assert parse_filename("abc_incoming_0_0.json") is None

    def test_no_match_empty(self):
        assert parse_filename("") is None

    def test_no_match_just_json(self):
        assert parse_filename("data.json") is None


# ─── Unit tests: validate_structure ─────────────────────────────────


class TestValidateStructure:
    def test_valid(self):
        assert validate_structure(_good_doc(), Path("test.json")) is None

    def test_not_a_dict(self):
        err = validate_structure([], Path("test.json"))
        assert err is not None
        assert "not a JSON object" in err

    def test_missing_node_format(self):
        err = validate_structure({"nodes": []}, Path("test.json"))
        assert err is not None

    def test_missing_nodes(self):
        err = validate_structure({"nodeFormat": list(STANDARD_NODE_FORMAT)}, Path("x"))
        assert err is not None

    def test_wrong_fields(self):
        doc = {"nodeFormat": ["a", "b"], "nodes": []}
        err = validate_structure(doc, Path("x"))
        assert err is not None
        assert "do not match" in err

    def test_node_wrong_length(self):
        doc = {
            "nodeFormat": list(STANDARD_NODE_FORMAT),
            "nodes": [[1, 2]],
        }
        err = validate_structure(doc, Path("x"))
        assert err is not None
        assert "2 elements" in err


# ─── Unit tests: file_hash ──────────────────────────────────────────


class TestFileHash:
    def test_same_content_same_hash(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("hello")
        assert file_hash(tmp_path / "a.txt") == file_hash(tmp_path / "b.txt")

    def test_different_content_different_hash(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        assert file_hash(tmp_path / "a.txt") != file_hash(tmp_path / "b.txt")


# ─── Integration: validate_raw — clean data ─────────────────────────


class TestValidateRawClean:
    def test_all_valid(self, tmp_path):
        raw = tmp_path / "raw"
        _write_raw(raw, "111_incoming_0_0.json", _good_doc(100))
        _write_raw(raw, "111_outgoing_0_0.json", _good_doc(200))

        errors, warnings, stats = validate_raw(raw)
        assert errors == []
        assert warnings == []
        assert stats["total_files"] == 2
        assert stats["valid_files"] == 2

    def test_empty_dir(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir()
        errors, warnings, stats = validate_raw(raw)
        assert errors == []
        assert len(warnings) == 1
        assert "No *.json" in warnings[0]
        assert stats["total_files"] == 0


# ─── Integration: bad filename pattern ──────────────────────────────


class TestValidateRawBadPattern:
    def test_non_standard_name_warns(self, tmp_path):
        raw = tmp_path / "raw"
        _write_raw(raw, "mydata.json")

        errors, warnings, stats = validate_raw(raw)
        assert errors == []
        assert stats["bad_pattern"] == 1
        assert any("does not match" in w for w in warnings)

    def test_valid_and_non_standard_mixed(self, tmp_path):
        raw = tmp_path / "raw"
        _write_raw(raw, "111_incoming_0_0.json", _good_doc(100))
        _write_raw(raw, "custom_name.json", _good_doc(200))

        errors, warnings, stats = validate_raw(raw)
        assert errors == []
        assert stats["valid_files"] == 2
        assert stats["bad_pattern"] == 1


# ─── Integration: bad JSON / structure ───────────────────────────────


class TestValidateRawBadContent:
    def test_malformed_json(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir(parents=True)
        (raw / "111_incoming_0_0.json").write_text("{broken!!")

        errors, warnings, stats = validate_raw(raw)
        assert stats["bad_json"] == 1
        assert len(errors) == 1

    def test_bad_structure(self, tmp_path):
        raw = tmp_path / "raw"
        write_json_file(raw / "111_incoming_0_0.json", {"wrong": True})

        errors, warnings, stats = validate_raw(raw)
        assert stats["bad_structure"] == 1
        assert len(errors) == 1


# ─── Integration: content-hash duplicates ────────────────────────────


class TestValidateRawHashDupes:
    def test_identical_files_detected(self, tmp_path):
        raw = tmp_path / "raw"
        doc = _good_doc()
        _write_raw(raw, "111_incoming_0_0.json", doc)
        _write_raw(raw, "222_incoming_0_0.json", doc)

        errors, warnings, stats = validate_raw(raw)
        assert stats["hash_dupes"] == 1
        assert any("Content-hash duplicate" in e for e in errors)

    def test_different_content_no_dupe(self, tmp_path):
        raw = tmp_path / "raw"
        _write_raw(raw, "111_incoming_0_0.json", _good_doc(100))
        _write_raw(raw, "222_incoming_0_0.json", _good_doc(200))

        errors, warnings, stats = validate_raw(raw)
        assert stats["hash_dupes"] == 0

    def test_three_identical_files(self, tmp_path):
        raw = tmp_path / "raw"
        doc = _good_doc()
        _write_raw(raw, "111_incoming_0_0.json", doc)
        _write_raw(raw, "222_incoming_0_0.json", doc)
        _write_raw(raw, "333_incoming_0_0.json", doc)

        errors, warnings, stats = validate_raw(raw)
        assert stats["hash_dupes"] == 2  # 3 files, 2 extra


# ─── Integration: slot collisions ───────────────────────────────────


class TestValidateRawSlotCollisions:
    def test_same_slot_different_content(self, tmp_path):
        """Two files whose names parse to the same slot but different content."""
        raw = tmp_path / "raw"
        # These would have to have identical filenames to be same-slot,
        # so this tests that two files with IDENTICAL parsed slots collide.
        # Since filenames must literally match the same slot, we need case
        # variation or something. Actually slot collision with different
        # filenames is impossible by definition (same parse = same name).
        # So this test uses the same filename written twice (second overwrites).
        # A real collision would require e.g. case differences: incoming vs INCOMING.
        _write_raw(raw, "111_incoming_0_0.json", _good_doc(100))
        _write_raw(raw, "111_INCOMING_0_0.json", _good_doc(200))

        errors, warnings, stats = validate_raw(raw)
        assert stats["slot_collisions"] == 1
        assert any("Slot collision" in e for e in errors)


# ─── Integration: orphan detection ───────────────────────────────────


class TestValidateRawOrphans:
    def test_orphan_detected(self, tmp_path):
        raw = tmp_path / "raw"
        output = tmp_path / "output"
        _write_raw(raw, "111_incoming_0_0.json")
        # This file exists in output/ but not in raw/
        write_json_file(output / "999_incoming_0_0.json", _good_doc())

        errors, warnings, stats = validate_raw(raw, output)
        assert stats["orphans"] == 1
        assert any("Orphan" in w for w in warnings)

    def test_no_orphans_when_matched(self, tmp_path):
        raw = tmp_path / "raw"
        output = tmp_path / "output"
        _write_raw(raw, "111_incoming_0_0.json")
        write_json_file(output / "111_incoming_0_0.json", _good_doc())

        errors, warnings, stats = validate_raw(raw, output)
        assert stats["orphans"] == 0

    def test_delete_orphans(self, tmp_path):
        raw = tmp_path / "raw"
        output = tmp_path / "output"
        _write_raw(raw, "111_incoming_0_0.json")
        orphan = output / "999_incoming_0_0.json"
        write_json_file(orphan, _good_doc())

        errors, warnings, stats = validate_raw(raw, output, delete_orphans=True)
        assert stats["orphans_deleted"] == 1
        assert not orphan.exists()

    def test_no_output_dir_skips_orphan_check(self, tmp_path):
        raw = tmp_path / "raw"
        _write_raw(raw, "111_incoming_0_0.json")

        errors, warnings, stats = validate_raw(raw, output_dir=None)
        assert stats["orphans"] == 0


# ─── Integration: main() CLI ────────────────────────────────────────


class TestMainCLI:
    def test_clean_run(self, tmp_path):
        raw = tmp_path / "raw"
        _write_raw(raw, "111_incoming_0_0.json", _good_doc(100))
        _write_raw(raw, "111_outgoing_0_0.json", _good_doc(200))

        ret = main(["--raw_dir", str(raw)])
        assert ret == 0

    def test_errors_exit_1(self, tmp_path):
        raw = tmp_path / "raw"
        raw.mkdir(parents=True)
        (raw / "bad.json").write_text("{broken!!")

        ret = main(["--raw_dir", str(raw)])
        assert ret == 1

    def test_strict_mode_warnings_exit_1(self, tmp_path):
        raw = tmp_path / "raw"
        _write_raw(raw, "custom_name.json")  # valid content, bad pattern

        ret = main(["--raw_dir", str(raw), "--strict"])
        assert ret == 1

    def test_nonstrict_warnings_exit_0(self, tmp_path):
        raw = tmp_path / "raw"
        _write_raw(raw, "custom_name.json")

        ret = main(["--raw_dir", str(raw)])
        assert ret == 0

    def test_nonexistent_dir(self, tmp_path):
        ret = main(["--raw_dir", str(tmp_path / "nope")])
        assert ret == 1

    def test_with_output_dir(self, tmp_path):
        raw = tmp_path / "raw"
        output = tmp_path / "output"
        _write_raw(raw, "111_incoming_0_0.json")
        write_json_file(output / "999_incoming_0_0.json", _good_doc())

        ret = main(["--raw_dir", str(raw), "--output_dir", str(output)])
        # Warnings (orphans) but no errors → exit 0
        assert ret == 0

    def test_with_output_dir_strict(self, tmp_path):
        raw = tmp_path / "raw"
        output = tmp_path / "output"
        _write_raw(raw, "111_incoming_0_0.json")
        write_json_file(output / "999_incoming_0_0.json", _good_doc())

        ret = main(["--raw_dir", str(raw), "--output_dir", str(output), "--strict"])
        # Orphan warning + strict → exit 1
        assert ret == 1
