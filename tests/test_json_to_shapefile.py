"""Tests for json_to_shapefile.py — unit tests, integration tests, and edge cases."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import shapefile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from json_to_shapefile import (
    _detect_direction,
    find_field_indices,
    _detect_attr_fields,
    validate_doc,
    convert_to_shapefile,
    main,
    FIELD_DEFS,
)
from tests.conftest import write_json_file, STANDARD_NODE_FORMAT


# ─── Unit tests: _detect_direction ──────────────────────────────────────


class TestDetectDirection:
    def test_incoming_mid(self):
        assert _detect_direction("123_incoming_0_0.json") == "incoming"

    def test_outgoing_mid(self):
        assert _detect_direction("123_outgoing_0_0.json") == "outgoing"

    def test_incoming_prefix(self):
        assert _detect_direction("incoming_data.json") == "incoming"

    def test_outgoing_prefix(self):
        assert _detect_direction("outgoing_data.json") == "outgoing"

    def test_case_insensitive(self):
        assert _detect_direction("123_INCOMING_0.json") == "incoming"
        assert _detect_direction("123_OUTGOING_0.json") == "outgoing"

    def test_unknown(self):
        assert _detect_direction("some_data.json") == "unknown"

    def test_empty(self):
        assert _detect_direction("") == "unknown"


# ─── Unit tests: find_field_indices ─────────────────────────────────────


class TestFindFieldIndices:
    def test_standard_format(self):
        result = find_field_indices(STANDARD_NODE_FORMAT)
        assert result["id"] == 0
        assert result["parentid"] == 1
        assert result["trips"] == 2
        assert result["frc"] == 3
        assert result["geometry"] == 4
        assert result["processingfailures"] == 5
        assert result["privacytrims"] == 6

    def test_with_trips_pct(self):
        fmt = list(STANDARD_NODE_FORMAT) + ["trips_pct"]
        result = find_field_indices(fmt)
        assert result["trips_pct"] == 7

    def test_case_insensitive_keys(self):
        """Keys are lowercased regardless of input case."""
        fmt = ["ID", "ParentId", "TRIPS"]
        result = find_field_indices(fmt)
        assert "id" in result
        assert "parentid" in result
        assert "trips" in result


# ─── Unit tests: _detect_attr_fields ────────────────────────────────────


class TestDetectAttrFields:
    def test_skips_geometry(self):
        field_map = find_field_indices(STANDARD_NODE_FORMAT)
        attrs = _detect_attr_fields(field_map)
        names = [name for name, _, _ in attrs]
        assert "geometry" not in names

    def test_includes_known_fields(self):
        field_map = find_field_indices(STANDARD_NODE_FORMAT)
        attrs = _detect_attr_fields(field_map)
        names = [name for name, _, _ in attrs]
        assert "id" in names
        assert "trips" in names
        assert "frc" in names

    def test_includes_trips_pct_when_present(self):
        fmt = list(STANDARD_NODE_FORMAT) + ["trips_pct"]
        field_map = find_field_indices(fmt)
        attrs = _detect_attr_fields(field_map)
        names = [name for name, _, _ in attrs]
        assert "trips_pct" in names

    def test_ignores_unknown_fields(self):
        fmt = list(STANDARD_NODE_FORMAT) + ["unknownField"]
        field_map = find_field_indices(fmt)
        attrs = _detect_attr_fields(field_map)
        names = [name for name, _, _ in attrs]
        assert "unknownfield" not in names

    def test_field_defs_match(self):
        """Each returned attr should reference a valid FIELD_DEFS entry."""
        field_map = find_field_indices(STANDARD_NODE_FORMAT)
        attrs = _detect_attr_fields(field_map)
        for lname, idx, fdef in attrs:
            assert lname in FIELD_DEFS
            assert fdef == FIELD_DEFS[lname]


# ─── Unit tests: validate_doc ───────────────────────────────────────────


class TestValidateDocShapefile:
    def test_valid(self, sample_doc):
        assert validate_doc(sample_doc, Path("test.json")) is None

    def test_not_a_dict(self):
        assert validate_doc([], Path("x")) is not None

    def test_missing_node_format(self):
        assert validate_doc({"nodes": []}, Path("x")) is not None

    def test_missing_nodes(self):
        assert validate_doc({"nodeFormat": []}, Path("x")) is not None

    def test_node_format_not_list(self):
        assert validate_doc({"nodeFormat": "bad", "nodes": []}, Path("x")) is not None

    def test_nodes_not_list(self):
        fmt = list(STANDARD_NODE_FORMAT)
        assert validate_doc({"nodeFormat": fmt, "nodes": "bad"}, Path("x")) is not None


# ─── Integration tests: single-file conversion ─────────────────────────


class TestSingleFileConversion:
    def test_basic_conversion(self, normalized_doc, tmp_path):
        """Convert a single doc → verify shapefile structure."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "shapefiles"
        write_json_file(input_dir / "test_incoming_0_0.json", normalized_doc)

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 0

        # The per-file mode creates output_dir/stem/stem.shp
        shp_path = output_dir / "test_incoming_0_0" / "test_incoming_0_0.shp"
        assert shp_path.exists()

        sf = shapefile.Reader(str(shp_path))
        assert sf.shapeType == shapefile.POLYLINE
        assert len(sf) == 3

        field_names = [f[0] for f in sf.fields[1:]]  # skip DeletionFlag
        assert "id" in field_names
        assert "trips" in field_names
        assert "trips_pct" in field_names

    def test_prj_file_created(self, normalized_doc, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "shapefiles"
        write_json_file(input_dir / "data.json", normalized_doc)

        main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])

        prj_path = output_dir / "data" / "data.prj"
        assert prj_path.exists()
        text = prj_path.read_text()
        assert "WGS_1984" in text

    def test_single_input_file(self, normalized_doc, tmp_path):
        """--input_file mode with a single file."""
        input_file = tmp_path / "single.json"
        output_dir = tmp_path / "shapefiles"
        write_json_file(input_file, normalized_doc)

        ret = main(["--input_file", str(input_file), "--output_dir", str(output_dir)])
        assert ret == 0

        shp_path = output_dir / "single" / "single.shp"
        assert shp_path.exists()
        sf = shapefile.Reader(str(shp_path))
        assert len(sf) == 3

    def test_attribute_values(self, normalized_doc, tmp_path):
        """Verify attribute values are correctly transferred."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "shapefiles"
        write_json_file(input_dir / "data.json", normalized_doc)

        main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])

        shp_path = output_dir / "data" / "data"
        sf = shapefile.Reader(str(shp_path))
        records = sf.records()

        field_names = [f[0] for f in sf.fields[1:]]
        id_idx = field_names.index("id")
        trips_idx = field_names.index("trips")
        trips_pct_idx = field_names.index("trips_pct")

        # First node: id=0, trips=100, trips_pct=50.0
        assert records[0][id_idx] == 0
        assert records[0][trips_idx] == 100
        assert records[0][trips_pct_idx] == pytest.approx(50.0, abs=0.01)


# ─── Integration tests: merge mode ─────────────────────────────────────


class TestMergeMode:
    def _setup_merge_input(self, normalized_doc, tmp_path):
        """Create incoming + outgoing JSON files in a temp dir."""
        input_dir = tmp_path / "input"
        write_json_file(
            input_dir / "123_incoming_0_0.json", normalized_doc
        )
        write_json_file(
            input_dir / "123_outgoing_0_0.json", normalized_doc
        )
        return input_dir

    def test_creates_two_shapefiles(self, normalized_doc, tmp_path):
        input_dir = self._setup_merge_input(normalized_doc, tmp_path)
        output_dir = tmp_path / "shapefiles"

        ret = main(["--input_dir", str(input_dir),
                     "--output_dir", str(output_dir), "--merge"])
        assert ret == 0

        assert (output_dir / "incoming.shp").exists()
        assert (output_dir / "outgoing.shp").exists()

    def test_feature_counts(self, normalized_doc, tmp_path):
        input_dir = self._setup_merge_input(normalized_doc, tmp_path)
        output_dir = tmp_path / "shapefiles"

        main(["--input_dir", str(input_dir),
              "--output_dir", str(output_dir), "--merge"])

        sf_in = shapefile.Reader(str(output_dir / "incoming"))
        sf_out = shapefile.Reader(str(output_dir / "outgoing"))
        # Each file has 3 nodes
        assert len(sf_in) == 3
        assert len(sf_out) == 3

    def test_source_field_present(self, normalized_doc, tmp_path):
        input_dir = self._setup_merge_input(normalized_doc, tmp_path)
        output_dir = tmp_path / "shapefiles"

        main(["--input_dir", str(input_dir),
              "--output_dir", str(output_dir), "--merge"])

        sf = shapefile.Reader(str(output_dir / "incoming"))
        field_names = [f[0] for f in sf.fields[1:]]
        assert "source" in field_names

        # Verify source value matches the stem of the input file
        src_idx = field_names.index("source")
        for rec in sf.records():
            assert rec[src_idx] == "123_incoming_0_0"

    def test_prj_files_created(self, normalized_doc, tmp_path):
        input_dir = self._setup_merge_input(normalized_doc, tmp_path)
        output_dir = tmp_path / "shapefiles"

        main(["--input_dir", str(input_dir),
              "--output_dir", str(output_dir), "--merge"])

        assert (output_dir / "incoming.prj").exists()
        assert (output_dir / "outgoing.prj").exists()

    def test_merge_multiple_files_same_direction(self, normalized_doc, tmp_path):
        """Two incoming files merged into one shapefile."""
        input_dir = tmp_path / "input"
        write_json_file(input_dir / "aaa_incoming_0_0.json", normalized_doc)
        write_json_file(input_dir / "bbb_incoming_0_0.json", normalized_doc)
        output_dir = tmp_path / "shapefiles"

        ret = main(["--input_dir", str(input_dir),
                     "--output_dir", str(output_dir), "--merge"])
        assert ret == 0

        sf = shapefile.Reader(str(output_dir / "incoming"))
        assert len(sf) == 6  # 3 + 3

        # Verify both source values are present
        field_names = [f[0] for f in sf.fields[1:]]
        src_idx = field_names.index("source")
        sources = {rec[src_idx] for rec in sf.records()}
        assert sources == {"aaa_incoming_0_0", "bbb_incoming_0_0"}

    def test_unknown_direction_bucket(self, normalized_doc, tmp_path):
        """File with no direction keyword → goes to 'unknown' bucket."""
        input_dir = tmp_path / "input"
        write_json_file(input_dir / "mydata.json", normalized_doc)
        output_dir = tmp_path / "shapefiles"

        ret = main(["--input_dir", str(input_dir),
                     "--output_dir", str(output_dir), "--merge"])
        assert ret == 0
        assert (output_dir / "unknown.shp").exists()


# ─── Edge cases and error handling ──────────────────────────────────────


class TestShapefileEdgeCases:
    def test_empty_input_dir(self, tmp_path):
        input_dir = tmp_path / "empty"
        input_dir.mkdir()
        output_dir = tmp_path / "shapefiles"

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 0

    def test_malformed_json(self, tmp_path):
        input_dir = tmp_path / "input"
        input_dir.mkdir(parents=True)
        (input_dir / "bad.json").write_text("{nope!!")
        output_dir = tmp_path / "shapefiles"

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 1

    def test_invalid_structure(self, tmp_path):
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "shapefiles"
        write_json_file(input_dir / "bad.json", {"wrong": True})

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 1

    def test_nonexistent_input_dir(self, tmp_path):
        ret = main(["--input_dir", str(tmp_path / "nope"),
                     "--output_dir", str(tmp_path / "out")])
        assert ret == 1

    def test_nonexistent_input_file(self, tmp_path):
        ret = main(["--input_file", str(tmp_path / "nope.json"),
                     "--output_dir", str(tmp_path / "out")])
        assert ret == 1

    def test_nodes_with_short_geometry_skipped(self, tmp_path):
        """Nodes with < 2 coordinate pairs are silently skipped."""
        doc = {
            "nodeFormat": list(STANDARD_NODE_FORMAT) + ["trips_pct"],
            "nodes": [
                # Valid: 2 coords
                [0, None, 100, 3, [[7.0, 47.0], [7.1, 47.1]], 0, 0, 50.0],
                # Invalid: only 1 coord pair
                [1, 0, 50, 2, [[8.0, 47.0]], 0, 0, 25.0],
                # Invalid: empty geometry
                [2, 0, 10, 1, [], 0, 0, 5.0],
                # Invalid: null geometry
                [3, 0, 10, 1, None, 0, 0, 5.0],
            ],
        }
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "shapefiles"
        write_json_file(input_dir / "data.json", doc)

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 0

        shp_path = output_dir / "data" / "data"
        sf = shapefile.Reader(str(shp_path))
        assert len(sf) == 1  # only the first node has valid geometry

    def test_mixed_valid_and_invalid_files(self, normalized_doc, tmp_path):
        """Good file processes, bad file is reported, exit code is 1."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "shapefiles"
        write_json_file(input_dir / "good.json", normalized_doc)
        write_json_file(input_dir / "bad.json", {"wrong": True})

        ret = main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])
        assert ret == 1
        # Good file still produced output
        assert (output_dir / "good" / "good.shp").exists()

    def test_input_file_and_input_dir_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            main(["--input_file", "a.json", "--input_dir", "dir",
                  "--output_dir", "out"])

    def test_geometry_is_polyline(self, normalized_doc, tmp_path):
        """All output shapes should be POLYLINE type."""
        input_dir = tmp_path / "input"
        output_dir = tmp_path / "shapefiles"
        write_json_file(input_dir / "data.json", normalized_doc)

        main(["--input_dir", str(input_dir), "--output_dir", str(output_dir)])

        shp_path = output_dir / "data" / "data"
        sf = shapefile.Reader(str(shp_path))
        for shape in sf.shapes():
            assert shape.shapeType == shapefile.POLYLINE
