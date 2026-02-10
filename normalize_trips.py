#!/usr/bin/env python3
"""
normalize_trips.py – Batch-process TomTom JSON files to add a normalized
trips percentage field (trips_pct) to every node.

Usage examples:
    # Process all JSON files from input/ and write results to output/
    python normalize_trips.py --input_dir ./input --output_dir ./output

    # Overwrite originals in-place
    python normalize_trips.py --input_dir ./data --inplace

    # Round to 4 decimal places, pretty-print output
    python normalize_trips.py --input_dir ./in --output_dir ./out --round 4 --pretty

    # Combine flags
    python normalize_trips.py --input_dir ./data --inplace --round 0 --pretty
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def read_json(path: Path) -> dict:
    """Read and parse a JSON file with UTF-8 encoding."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def validate_doc(doc: dict, path: Path) -> str | None:
    """Validate that doc has the required structure.

    Returns an error message string on failure, or None on success.
    """
    if not isinstance(doc, dict):
        return f"{path}: top-level value is not a JSON object"

    if "nodeFormat" not in doc:
        return f"{path}: missing required key 'nodeFormat'"
    if "nodes" not in doc:
        return f"{path}: missing required key 'nodes'"

    node_format = doc["nodeFormat"]
    if not isinstance(node_format, list):
        return f"{path}: 'nodeFormat' is not an array"

    lower_fields = [f.lower() if isinstance(f, str) else f for f in node_format]
    expected = ["id", "parentid", "trips", "frc", "geometry",
                "processingfailures", "privacytrims"]
    if lower_fields != expected:
        return (
            f"{path}: 'nodeFormat' fields do not match expected schema. "
            f"Got {node_format}, expected (case-insensitive) {expected}"
        )

    if not isinstance(doc["nodes"], list):
        return f"{path}: 'nodes' is not an array"

    expected_len = len(node_format)
    for i, node in enumerate(doc["nodes"]):
        if not isinstance(node, list):
            return f"{path}: node[{i}] is not an array"
        if len(node) != expected_len:
            return (
                f"{path}: node[{i}] has {len(node)} elements, "
                f"expected {expected_len}"
            )

    return None


def process_doc(doc: dict, round_n: int) -> dict:
    """Add trips_pct to nodeFormat and every node array.

    Computes trips_pct = (trips / max_trips) * 100, rounded to round_n
    decimal places.  Returns a new dict (shallow copy of top-level keys,
    nodes are mutated in place for efficiency).
    """
    trips_index = 2  # "trips" is always the 3rd field

    # Find max_trips, ignoring None/null values
    max_trips = 0
    for node in doc["nodes"]:
        val = node[trips_index]
        if val is not None and val > max_trips:
            max_trips = val

    # Compute trips_pct for each node
    for node in doc["nodes"]:
        val = node[trips_index]
        if val is None or max_trips == 0:
            node.append(0.0)
        else:
            node.append(round((val / max_trips) * 100, round_n))

    # Append the new field name to nodeFormat
    doc["nodeFormat"] = doc["nodeFormat"] + ["trips_pct"]

    return doc


def write_json(path: Path, doc: dict, pretty: bool = False) -> None:
    """Write a dict as JSON with UTF-8 encoding."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        if pretty:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        else:
            json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Batch-add normalized trips_pct to TomTom JSON node files."
    )
    parser.add_argument(
        "--input_dir", required=True, type=Path,
        help="Folder containing *.json input files.",
    )
    parser.add_argument(
        "--output_dir", type=Path, default=None,
        help="Folder to write processed files (same base names).",
    )
    parser.add_argument(
        "--inplace", action="store_true",
        help="Overwrite original files instead of writing to --output_dir.",
    )
    parser.add_argument(
        "--round", type=int, default=2, dest="round_n",
        help="Decimal places for trips_pct (default: 2).",
    )
    parser.add_argument(
        "--pretty", action="store_true",
        help="Pretty-print output JSON (default: compact).",
    )
    args = parser.parse_args(argv)

    # Validate argument combinations
    if not args.inplace and args.output_dir is None:
        parser.error("Provide --output_dir or --inplace.")
    if args.inplace and args.output_dir is not None:
        parser.error("--inplace and --output_dir are mutually exclusive.")

    input_dir: Path = args.input_dir
    if not input_dir.is_dir():
        print(f"Error: input directory does not exist: {input_dir}", file=sys.stderr)
        return 1

    json_files = sorted(input_dir.glob("*.json"))
    if not json_files:
        print(f"Warning: no *.json files found in {input_dir}", file=sys.stderr)
        return 0

    failures: list[str] = []
    processed = 0

    for filepath in json_files:
        # Read
        try:
            doc = read_json(filepath)
        except (json.JSONDecodeError, OSError) as exc:
            msg = f"{filepath}: failed to read/parse — {exc}"
            failures.append(msg)
            print(msg, file=sys.stderr)
            continue

        # Validate
        err = validate_doc(doc, filepath)
        if err is not None:
            failures.append(err)
            print(err, file=sys.stderr)
            continue

        # Process
        process_doc(doc, args.round_n)

        # Write
        if args.inplace:
            out_path = filepath
        else:
            out_path = args.output_dir / filepath.name

        try:
            write_json(out_path, doc, pretty=args.pretty)
        except OSError as exc:
            msg = f"{out_path}: failed to write — {exc}"
            failures.append(msg)
            print(msg, file=sys.stderr)
            continue

        processed += 1

    # Summary
    total = len(json_files)
    print(f"Processed {processed}/{total} file(s).", file=sys.stderr)
    if failures:
        print(f"\n{len(failures)} failure(s):", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
