#!/usr/bin/env python3
"""
json_to_shapefile.py – Convert TomTom JSON node files to ESRI Shapefiles
for use in ArcGIS Pro.

Each node's geometry (array of [lon, lat] pairs) becomes a PolyLine feature
with attribute fields for all node properties.

Requirements:
    pip install pyshp

Usage examples:
    # Convert a single file to its own shapefile
    python json_to_shapefile.py --input_file data.json --output_dir ./shapefiles

    # Batch-convert: one shapefile per JSON file
    python json_to_shapefile.py --input_dir ./data --output_dir ./shapefiles

    # Merge all files into a single shapefile (adds 'source' field)
    python json_to_shapefile.py --input_dir ./data --output_dir ./shapefiles --merge

    # Merged output with custom shapefile name
    python json_to_shapefile.py --input_dir ./data --output_dir ./shapefiles --merge --merge_name aargau_all
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import shapefile

# WGS 84 projection string — ArcGIS Pro reads the .prj sidecar file to
# assign a coordinate system automatically.
WGS84_PRJ = (
    'GEOGCS["GCS_WGS_1984",'
    'DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],'
    'UNIT["Degree",0.0174532925199433]]'
)

# Field-name mapping: JSON field name -> (shapefile field name, type, size, decimals)
# Shapefile field names are limited to 10 characters.
FIELD_DEFS = {
    "id":                 ("id",          "N", 10, 0),
    "parentid":           ("parentId",    "N", 10, 0),
    "trips":              ("trips",       "N", 10, 0),
    "frc":                ("frc",         "N", 5,  0),
    "processingfailures": ("procFail",    "N", 10, 0),
    "privacytrims":       ("privTrims",   "N", 10, 0),
    "trips_pct":          ("trips_pct",   "N", 12, 4),
}


def read_json(path: Path) -> dict:
    """Read and parse a JSON file with UTF-8 encoding."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_doc(doc: dict, path: Path) -> str | None:
    """Validate minimum required structure. Returns error message or None."""
    if not isinstance(doc, dict):
        return f"{path}: top-level value is not a JSON object"
    if "nodeFormat" not in doc:
        return f"{path}: missing required key 'nodeFormat'"
    if "nodes" not in doc:
        return f"{path}: missing required key 'nodes'"
    if not isinstance(doc["nodeFormat"], list) or not isinstance(doc["nodes"], list):
        return f"{path}: 'nodeFormat' and 'nodes' must be arrays"
    return None


def find_field_indices(node_format: list[str]) -> dict[str, int]:
    """Map lowercase field names to their index in the node array."""
    return {name.lower(): i for i, name in enumerate(node_format)}


def _detect_attr_fields(field_map: dict[str, int]) -> list[tuple[str, int, tuple]]:
    """Build ordered list of (lowercase_name, index, field_def) for attributes."""
    attr_fields = []
    for lname, idx in field_map.items():
        if lname == "geometry":
            continue
        if lname in FIELD_DEFS:
            attr_fields.append((lname, idx, FIELD_DEFS[lname]))
    return attr_fields


def _write_prj(output_path: Path) -> None:
    """Write WGS 84 .prj sidecar."""
    prj_path = output_path.with_suffix(".prj")
    prj_path.write_text(WGS84_PRJ, encoding="utf-8")


def convert_to_shapefile(doc: dict, output_path: Path) -> int:
    """Convert a single JSON document to its own shapefile.

    Returns number of features written.
    """
    node_format = doc["nodeFormat"]
    nodes = doc["nodes"]
    field_map = find_field_indices(node_format)

    geom_idx = field_map.get("geometry")
    attr_fields = _detect_attr_fields(field_map)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    w = shapefile.Writer(str(output_path))
    w.shapeType = shapefile.POLYLINE
    w.autoBalance = 1

    for _, _, (fname, ftype, fsize, fdec) in attr_fields:
        w.field(fname, ftype, size=fsize, decimal=fdec)

    count = 0
    for node in nodes:
        coords = node[geom_idx] if geom_idx is not None else None
        if not coords or not isinstance(coords, list) or len(coords) < 2:
            continue
        w.line([coords])
        rec = [node[idx] if node[idx] is not None else None for _, idx, _ in attr_fields]
        w.record(*rec)
        count += 1

    w.close()
    _write_prj(output_path)
    return count


def append_to_writer(
    w: shapefile.Writer,
    doc: dict,
    source_name: str,
    attr_fields: list[tuple[str, int, tuple]],
) -> int:
    """Append all features from one document to a shared Writer.

    Returns number of features appended.
    """
    field_map = find_field_indices(doc["nodeFormat"])
    geom_idx = field_map.get("geometry")

    # Build index mapping: for each target attr field, find index in this doc
    doc_indices = {}
    for lname, _target_idx, _ in attr_fields:
        doc_indices[lname] = field_map.get(lname)

    count = 0
    for node in doc["nodes"]:
        coords = node[geom_idx] if geom_idx is not None else None
        if not coords or not isinstance(coords, list) or len(coords) < 2:
            continue
        w.line([coords])
        rec = []
        for lname, _, _ in attr_fields:
            idx = doc_indices.get(lname)
            if idx is not None:
                val = node[idx]
                rec.append(val if val is not None else None)
            else:
                rec.append(None)
        rec.append(source_name)
        w.record(*rec)
        count += 1

    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert TomTom JSON node files to ESRI Shapefiles."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--input_file", type=Path,
        help="Single JSON file to convert.",
    )
    group.add_argument(
        "--input_dir", type=Path,
        help="Folder containing *.json files to batch-convert.",
    )
    parser.add_argument(
        "--output_dir", required=True, type=Path,
        help="Folder to write shapefiles.",
    )
    parser.add_argument(
        "--merge", action="store_true",
        help="Combine all input files into a single shapefile.",
    )
    parser.add_argument(
        "--merge_name", type=str, default="merged",
        help="Base name for the merged shapefile (default: 'merged').",
    )
    args = parser.parse_args(argv)

    # Collect input files
    if args.input_file:
        if not args.input_file.is_file():
            print(f"Error: file not found: {args.input_file}", file=sys.stderr)
            return 1
        json_files = [args.input_file]
    else:
        if not args.input_dir.is_dir():
            print(f"Error: directory not found: {args.input_dir}", file=sys.stderr)
            return 1
        json_files = sorted(args.input_dir.glob("*.json"))
        if not json_files:
            print(f"Warning: no *.json files in {args.input_dir}", file=sys.stderr)
            return 0

    failures: list[str] = []
    total_features = 0

    if args.merge:
        # ── Merged mode: single shapefile for all files ──
        # Peek at the first valid file to determine fields
        first_doc = None
        for filepath in json_files:
            try:
                doc = read_json(filepath)
            except (json.JSONDecodeError, OSError):
                continue
            if validate_doc(doc, filepath) is None:
                first_doc = doc
                break

        if first_doc is None:
            print("Error: no valid JSON files found.", file=sys.stderr)
            return 1

        field_map = find_field_indices(first_doc["nodeFormat"])
        attr_fields = _detect_attr_fields(field_map)

        output_path = args.output_dir / args.merge_name
        output_path.parent.mkdir(parents=True, exist_ok=True)
        w = shapefile.Writer(str(output_path))
        w.shapeType = shapefile.POLYLINE
        w.autoBalance = 1

        for _, _, (fname, ftype, fsize, fdec) in attr_fields:
            w.field(fname, ftype, size=fsize, decimal=fdec)
        # source field: filename stem, up to 80 chars
        w.field("source", "C", size=80)

        for filepath in json_files:
            try:
                doc = read_json(filepath)
            except (json.JSONDecodeError, OSError) as exc:
                msg = f"{filepath}: failed to read — {exc}"
                failures.append(msg)
                print(msg, file=sys.stderr)
                continue

            err = validate_doc(doc, filepath)
            if err is not None:
                failures.append(err)
                print(err, file=sys.stderr)
                continue

            source_name = filepath.stem
            try:
                count = append_to_writer(w, doc, source_name, attr_fields)
            except Exception as exc:
                msg = f"{filepath}: conversion failed — {exc}"
                failures.append(msg)
                print(msg, file=sys.stderr)
                continue

            total_features += count
            print(f"{filepath.name}: {count} features", file=sys.stderr)

        w.close()
        _write_prj(output_path)

        total = len(json_files)
        ok = total - len(failures)
        print(
            f"\nMerged {ok}/{total} file(s) -> {output_path}.shp "
            f"({total_features} features).",
            file=sys.stderr,
        )

    else:
        # ── Per-file mode: one shapefile per JSON file ──
        for filepath in json_files:
            try:
                doc = read_json(filepath)
            except (json.JSONDecodeError, OSError) as exc:
                msg = f"{filepath}: failed to read — {exc}"
                failures.append(msg)
                print(msg, file=sys.stderr)
                continue

            err = validate_doc(doc, filepath)
            if err is not None:
                failures.append(err)
                print(err, file=sys.stderr)
                continue

            stem = filepath.stem
            output_path = args.output_dir / stem / stem
            try:
                count = convert_to_shapefile(doc, output_path)
            except Exception as exc:
                msg = f"{filepath}: conversion failed — {exc}"
                failures.append(msg)
                print(msg, file=sys.stderr)
                continue

            total_features += count
            print(f"{filepath.name}: {count} features -> {output_path}.shp", file=sys.stderr)

        total = len(json_files)
        ok = total - len(failures)
        print(f"\nConverted {ok}/{total} file(s), {total_features} total features.", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} failure(s):", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
