"""Tests for normalize_trips.py — unit tests, integration tests, and edge cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the repo root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from normalize_trips import process_doc, validate_doc, main
from tests.conftest import write_json_file, STANDARD_NODE_FORMAT


# ─── Unit tests: validate_doc ───────────────────────────────────────────


class TestValidateDoc:
    def test_valid_doc(self, sample_doc):
        assert validate_doc(sample_doc, Path("test.json")) is None

    def test_not_a_dict(self):
        err = validate_doc([], Path("test.json"))
        assert err is not None
        assert "not a JSON object" in err

    def test_missing_node_format(self):
        doc = {"nodes": []}
        err = validate_doc(doc, Path("test.json"))
        assert err is not None
        assert "nodeFormat" in err

    def test_missing_nodes(self):
        doc = {"nodeFormat": STANDARD_NODE_FORMAT}
        err = validate_doc(doc, Path("test.json"))
        assert err is not None
        assert "nodes" in err

    def test_node_format_not_a_list(self):
        doc = {"nodeFormat": "not_a_list", "nodes": []}
        err = validate_doc(doc, Path("test.json"))
        assert err is not None
        assert "not an array" in err

    def test_wrong_field_order(self):
        doc = {
            "nodeFormat": ["trips", "id", "parentId", "frc",
                           "geometry", "processingFailures", "privacyTrims"],
            "nodes": [],
        }
        err = validate_doc(doc, Path("test.json"))
        assert err is not None
        assert "do not match" in err

    def test_node_wrong_element_count(self):
        doc = {
            "nodeFormat": list(STANDARD_NODE_FORMAT),
            "nodes": [[1, 2, 3]],  # too few elements
        }
        err = validate_doc(doc, Path("test.json"))
        assert err is not None
        assert "3 elements" in err

    def test_node_not_an_array(self):
        doc = {
            "nodeFormat": list(STANDARD_NODE_FORMAT),
            "nodes": ["not_a_node"],
        }
        err = validate_doc(doc, Path("test.json"))
        assert err is not None
        assert "not an array" in err

    def test_nodes_not_a_list(self):
        doc = {"nodeFormat": list(STANDARD_NODE_FORMAT), "nodes": "not_a_list"}
        err = validate_doc(doc, Path("test.json"))
        assert err is not None
        assert "not an array" in err


# ─── Unit tests: process_doc ────────────────────────────────────────────


class TestProcessDoc:
    def test_normal_percentages(self, sample_doc):
        """trips=[100, 50, 200] → trips_pct=[50.0, 25.0, 100.0]"""
        result = process_doc(sample_doc, round_n=2)
        assert "trips_pct" in result["nodeFormat"]
        pct_idx = result["nodeFormat"].index("trips_pct")
        values = [node[pct_idx] for node in result["nodes"]]
        assert values == [50.0, 25.0, 100.0]

    def test_all_zeros(self, sample_doc_all_zero):
        """All trips=0 → all trips_pct=0.0 (no division by zero)."""
        result = process_doc(sample_doc_all_zero, round_n=2)
        pct_idx = result["nodeFormat"].index("trips_pct")
        values = [node[pct_idx] for node in result["nodes"]]
        assert values == [0.0, 0.0]

    def test_null_trips(self, sample_doc_with_nulls):
        """trips=[100, None, 0] → trips_pct=[100.0, 0.0, 0.0]"""
        result = process_doc(sample_doc_with_nulls, round_n=2)
        pct_idx = result["nodeFormat"].index("trips_pct")
        values = [node[pct_idx] for node in result["nodes"]]
        assert values == [100.0, 0.0, 0.0]

    def test_rounding_zero_decimals(self, sample_doc):
        result = process_doc(sample_doc, round_n=0)
        pct_idx = result["nodeFormat"].index("trips_pct")
        values = [node[pct_idx] for node in result["nodes"]]
        assert values == [50.0, 25.0, 100.0]

    def test_rounding_four_decimals(self):
        """Verify rounding with values that produce long decimals."""
        doc = {
            "nodeFormat": list(STANDARD_NODE_FORMAT),
            "nodes": [
                [0, None, 33, 3, [[0, 0], [1, 1]], 0, 0],
                [1, 0, 100, 2, [[0, 0], [1, 1]], 0, 0],
            ],
        }
        result = process_doc(doc, round_n=4)
        pct_idx = result["nodeFormat"].index("trips_pct")
        # 33/100 * 100 = 33.0 exactly, but test the mechanism works
        assert result["nodes"][0][pct_idx] == 33.0
        assert result["nodes"][1][pct_idx] == 100.0

    def test_appends_field_to_node_format(self, sample_doc):
        original_len = len(sample_doc["nodeFormat"])
        process_doc(sample_doc, round_n=2)
        assert len(sample_doc["nodeFormat"]) == original_len + 1
        assert sample_doc["nodeFormat"][-1] == "trips_pct"

    def test_single_node(self):
        """A single node with trips > 0 → trips_pct = 100.0."""
        doc = {
            "nodeFormat": list(STANDARD_NODE_FORMAT),
            "nodes": [[0, None, 42, 3, [[0, 0], [1, 1]], 0, 0]],
        }
        result = process_doc(doc, round_n=2)
        pct_idx = result["nodeFormat"].index("trips_pct")
        assert result["nodes"][0][pct_idx] == 100.0


# ─── Integration tests: main() via CLI args ─────────────────────────────


class TestNormalizeIntegration:
    def test_output_dir_mode(self, sample_doc, tmp_path):
        """Full round-trip: write JSON, run main(), read output."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        write_json_file(input_dir / "data.json", sample_doc)

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 0

        out_file = output_dir / "data.json"
        assert out_file.exists()

        with open(out_file) as f:
            result = json.load(f)

        assert "trips_pct" in result["nodeFormat"]
        assert len(result["nodes"]) == 3
        # Verify values
        pct_idx = result["nodeFormat"].index("trips_pct")
        values = [node[pct_idx] for node in result["nodes"]]
        assert values == [50.0, 25.0, 100.0]

    def test_inplace_mode(self, sample_doc, tmp_path):
        input_dir = tmp_path / "data"
        filepath = write_json_file(input_dir / "test.json", sample_doc)

        ret = main(["--input_dir", str(input_dir), "--inplace"])
        assert ret == 0

        with open(filepath) as f:
            result = json.load(f)
        assert "trips_pct" in result["nodeFormat"]

    def test_pretty_print(self, sample_doc, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        write_json_file(input_dir / "data.json", sample_doc)

        main(["--input_dir", str(input_dir), "--output_dir", str(output_dir),
              "--pretty"])

        text = (output_dir / "data.json").read_text()
        # Pretty-printed JSON has newlines and indentation
        assert "\n" in text
        assert "  " in text

    def test_compact_output(self, sample_doc, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        write_json_file(input_dir / "data.json", sample_doc)

        main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])

        text = (output_dir / "data.json").read_text().strip()
        # Compact JSON has no spaces after separators (except within values)
        assert "\n" not in text.rstrip("\n")

    def test_custom_rounding(self, sample_doc, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        write_json_file(input_dir / "data.json", sample_doc)

        main(["--input_dir", str(input_dir), "--output_dir", str(output_dir),
              "--round", "0"])

        with open(output_dir / "data.json") as f:
            result = json.load(f)
        pct_idx = result["nodeFormat"].index("trips_pct")
        for node in result["nodes"]:
            assert node[pct_idx] == int(node[pct_idx])

    def test_multiple_files(self, sample_doc, tmp_path):
        """Process multiple JSON files in one batch."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        write_json_file(input_dir / "a.json", sample_doc)
        write_json_file(input_dir / "b.json", sample_doc)

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 0
        assert (output_dir / "a.json").exists()
        assert (output_dir / "b.json").exists()


# ─── Edge cases and error handling ──────────────────────────────────────


class TestNormalizeEdgeCases:
    def test_empty_input_dir(self, tmp_path):
        """Empty directory → return 0, no crash."""
        input_dir = tmp_path / "empty"
        input_dir.mkdir()
        output_dir = tmp_path / "output"

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 0

    def test_malformed_json(self, tmp_path):
        """Invalid JSON → skip file, return 1."""
        input_dir = tmp_path / "input"
        input_dir.mkdir(parents=True)
        (input_dir / "bad.json").write_text("{invalid json!!")
        output_dir = tmp_path / "output"

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 1

    def test_invalid_structure(self, tmp_path):
        """Valid JSON but wrong structure → skip file, return 1."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        write_json_file(input_dir / "bad.json", {"wrong": "structure"})

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 1

    def test_mixed_valid_and_invalid(self, sample_doc, tmp_path):
        """One good file + one bad file → processes good, reports failure."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        write_json_file(input_dir / "good.json", sample_doc)
        write_json_file(input_dir / "bad.json", {"wrong": "structure"})

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 1  # reports failures
        assert (output_dir / "good.json").exists()  # but still processes the good one

    def test_nonexistent_input_dir(self, tmp_path):
        ret = main(["--input_dir", str(tmp_path / "nope"),
                     "--output_dir", str(tmp_path / "out")])
        assert ret == 1

    def test_inplace_and_output_dir_conflict(self):
        with pytest.raises(SystemExit):
            main(["--input_dir", ".", "--output_dir", "out", "--inplace"])

    def test_no_output_option(self):
        with pytest.raises(SystemExit):
            main(["--input_dir", "."])
