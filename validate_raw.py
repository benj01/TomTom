#!/usr/bin/env python3
"""
validate_raw.py – Pre-flight validation of the raw/ directory before running
the TomTom processing pipeline.

Checks performed:
  1. Filename pattern:  {deviceId}_{direction}_{x}_{y}.json
  2. JSON readability and structural validity
  3. Duplicate detection:
     a. Content-hash duplicates (identical files with different names)
     b. Slot collisions (same deviceId+direction+x+y, different content)
  4. Orphan detection:  output/ files with no corresponding raw/ source

Usage examples:
    # Validate raw/ and report issues
    python validate_raw.py --raw_dir ./raw

    # Also check for orphans in output/
    python validate_raw.py --raw_dir ./raw --output_dir ./output

    # Strict mode: exit 1 on any warning (useful for CI / scripting)
    python validate_raw.py --raw_dir ./raw --strict

    # Delete orphans automatically
    python validate_raw.py --raw_dir ./raw --output_dir ./output --delete-orphans
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# Expected naming pattern: {numeric_id}_{incoming|outgoing}_{x}_{y}.json
FILENAME_RE = re.compile(
    r"^(?P<device>\d+)_(?P<direction>incoming|outgoing)_(?P<x>\d+)_(?P<y>\d+)\.json$",
    re.IGNORECASE,
)

EXPECTED_FIELDS = ["id", "parentid", "trips", "frc", "geometry",
                   "processingfailures", "privacytrims"]


def parse_filename(name: str) -> dict | None:
    """Parse a filename into its components. Returns None if it doesn't match."""
    m = FILENAME_RE.match(name)
    if not m:
        return None
    return {
        "device": m.group("device"),
        "direction": m.group("direction").lower(),
        "x": m.group("x"),
        "y": m.group("y"),
    }


def file_hash(path: Path) -> str:
    """Return SHA-256 hex digest of a file's contents."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def validate_structure(doc: object, path: Path) -> str | None:
    """Check that a parsed JSON doc has the required TomTom structure.

    Returns an error message string on failure, or None on success.
    """
    if not isinstance(doc, dict):
        return f"{path.name}: top-level value is not a JSON object"
    if "nodeFormat" not in doc:
        return f"{path.name}: missing required key 'nodeFormat'"
    if "nodes" not in doc:
        return f"{path.name}: missing required key 'nodes'"
    nf = doc["nodeFormat"]
    if not isinstance(nf, list):
        return f"{path.name}: 'nodeFormat' is not an array"
    if not isinstance(doc["nodes"], list):
        return f"{path.name}: 'nodes' is not an array"
    lower = [f.lower() if isinstance(f, str) else f for f in nf]
    if lower != EXPECTED_FIELDS:
        return (
            f"{path.name}: nodeFormat fields do not match expected schema "
            f"(got {nf})"
        )
    expected_len = len(nf)
    for i, node in enumerate(doc["nodes"]):
        if not isinstance(node, list):
            return f"{path.name}: node[{i}] is not an array"
        if len(node) != expected_len:
            return (
                f"{path.name}: node[{i}] has {len(node)} elements, "
                f"expected {expected_len}"
            )
    return None


def validate_raw(
    raw_dir: Path,
    output_dir: Path | None = None,
    delete_orphans: bool = False,
) -> tuple[list[str], list[str], dict]:
    """Run all validation checks on raw_dir.

    Returns (errors, warnings, stats) where:
      - errors:   issues that would corrupt the pipeline output
      - warnings: non-critical issues worth noting
      - stats:    summary counters
    """
    errors: list[str] = []
    warnings: list[str] = []
    stats = {
        "total_files": 0,
        "valid_files": 0,
        "bad_pattern": 0,
        "bad_json": 0,
        "bad_structure": 0,
        "hash_dupes": 0,
        "slot_collisions": 0,
        "orphans": 0,
        "orphans_deleted": 0,
    }

    json_files = sorted(raw_dir.glob("*.json"))
    stats["total_files"] = len(json_files)

    if not json_files:
        warnings.append(f"No *.json files found in {raw_dir}")
        return errors, warnings, stats

    # ── Pass 1: pattern check + JSON readability + structure ─────────
    valid_files: list[Path] = []
    parsed_names: dict[Path, dict] = {}

    for fp in json_files:
        parts = parse_filename(fp.name)
        if parts is None:
            warnings.append(
                f"{fp.name}: filename does not match expected pattern "
                f"{{deviceId}}_{{direction}}_{{x}}_{{y}}.json"
            )
            stats["bad_pattern"] += 1

        try:
            with open(fp, encoding="utf-8") as f:
                doc = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            errors.append(f"{fp.name}: cannot read/parse — {exc}")
            stats["bad_json"] += 1
            continue

        err = validate_structure(doc, fp)
        if err is not None:
            errors.append(err)
            stats["bad_structure"] += 1
            continue

        valid_files.append(fp)
        if parts is not None:
            parsed_names[fp] = parts

    stats["valid_files"] = len(valid_files)

    # ── Pass 2: content-hash duplicates ──────────────────────────────
    hashes: dict[str, list[Path]] = {}
    for fp in valid_files:
        h = file_hash(fp)
        hashes.setdefault(h, []).append(fp)

    for h, paths in hashes.items():
        if len(paths) > 1:
            names = ", ".join(p.name for p in paths)
            errors.append(
                f"Content-hash duplicate: the following files are identical: {names}"
            )
            stats["hash_dupes"] += len(paths) - 1

    # ── Pass 3: slot collisions (same device+dir+x+y, different content) ─
    slots: dict[str, list[Path]] = {}
    for fp, parts in parsed_names.items():
        slot_key = f"{parts['device']}_{parts['direction']}_{parts['x']}_{parts['y']}"
        slots.setdefault(slot_key, []).append(fp)

    for key, paths in slots.items():
        if len(paths) > 1:
            names = ", ".join(p.name for p in paths)
            errors.append(
                f"Slot collision for [{key}]: {names}"
            )
            stats["slot_collisions"] += len(paths) - 1

    # ── Pass 4: orphan detection in output_dir ───────────────────────
    if output_dir is not None and output_dir.is_dir():
        raw_names = {fp.name for fp in json_files}
        for out_fp in sorted(output_dir.glob("*.json")):
            if out_fp.name not in raw_names:
                warnings.append(f"Orphan in {output_dir.name}/: {out_fp.name}")
                stats["orphans"] += 1
                if delete_orphans:
                    out_fp.unlink()
                    stats["orphans_deleted"] += 1

    return errors, warnings, stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Pre-flight validation of raw TomTom JSON files."
    )
    parser.add_argument(
        "--raw_dir", required=True, type=Path,
        help="Directory containing raw *.json files.",
    )
    parser.add_argument(
        "--output_dir", type=Path, default=None,
        help="Normalized output directory (checked for orphans).",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as errors (exit 1 on any issue).",
    )
    parser.add_argument(
        "--delete-orphans", action="store_true",
        help="Delete orphan files from output_dir.",
    )
    args = parser.parse_args(argv)

    raw_dir: Path = args.raw_dir
    if not raw_dir.is_dir():
        print(f"Error: directory not found: {raw_dir}", file=sys.stderr)
        return 1

    errors, warnings, stats = validate_raw(
        raw_dir, args.output_dir, args.delete_orphans
    )

    # ── Report ───────────────────────────────────────────────────────
    print(f"Files scanned:  {stats['total_files']}")
    print(f"  Valid:        {stats['valid_files']}")
    if stats["bad_pattern"]:
        print(f"  Bad pattern:  {stats['bad_pattern']}")
    if stats["bad_json"]:
        print(f"  Bad JSON:     {stats['bad_json']}")
    if stats["bad_structure"]:
        print(f"  Bad structure:{stats['bad_structure']}")
    if stats["hash_dupes"]:
        print(f"  Hash dupes:   {stats['hash_dupes']}")
    if stats["slot_collisions"]:
        print(f"  Slot clashes: {stats['slot_collisions']}")
    if stats["orphans"]:
        print(f"  Orphans:      {stats['orphans']}")
    if stats["orphans_deleted"]:
        print(f"  Deleted:      {stats['orphans_deleted']}")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for msg in errors:
            print(f"  ERROR  {msg}")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for msg in warnings:
            print(f"  WARN   {msg}")

    if not errors and not warnings:
        print("\nAll checks passed.")

    # Exit code
    if errors:
        return 1
    if warnings and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
