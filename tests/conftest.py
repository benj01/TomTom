"""Shared fixtures for TomTom pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _make_node(
    node_id: int,
    parent_id: int | None,
    trips: int | None,
    frc: int,
    coords: list[list[float]],
    proc_fail: int = 0,
    priv_trims: int = 0,
) -> list:
    """Build a single node array matching the standard nodeFormat."""
    return [node_id, parent_id, trips, frc, coords, proc_fail, priv_trims]


STANDARD_NODE_FORMAT = [
    "id", "parentId", "trips", "frc", "geometry",
    "processingFailures", "privacyTrims",
]

# A minimal but realistic geometry (3 coordinate pairs)
SAMPLE_COORDS_A = [[7.81482, 47.52665], [7.81478, 47.52665], [7.81470, 47.52660]]
SAMPLE_COORDS_B = [[8.12300, 47.40000], [8.12310, 47.40010]]
SAMPLE_COORDS_C = [[8.50000, 47.30000], [8.50010, 47.30010], [8.50020, 47.30020]]


@pytest.fixture()
def sample_doc() -> dict:
    """A valid TomTom JSON document with 3 nodes."""
    return {
        "nodeFormat": list(STANDARD_NODE_FORMAT),
        "nodes": [
            _make_node(0, None, 100, 3, SAMPLE_COORDS_A, 10, 20),
            _make_node(1, 0, 50, 2, SAMPLE_COORDS_B, 5, 10),
            _make_node(2, 0, 200, 1, SAMPLE_COORDS_C, 0, 0),
        ],
    }


@pytest.fixture()
def sample_doc_with_nulls() -> dict:
    """A valid doc where some trips values are None."""
    return {
        "nodeFormat": list(STANDARD_NODE_FORMAT),
        "nodes": [
            _make_node(0, None, 100, 3, SAMPLE_COORDS_A),
            _make_node(1, 0, None, 2, SAMPLE_COORDS_B),
            _make_node(2, 0, 0, 1, SAMPLE_COORDS_C),
        ],
    }


@pytest.fixture()
def sample_doc_all_zero() -> dict:
    """A valid doc where all trips values are 0."""
    return {
        "nodeFormat": list(STANDARD_NODE_FORMAT),
        "nodes": [
            _make_node(0, None, 0, 3, SAMPLE_COORDS_A),
            _make_node(1, 0, 0, 2, SAMPLE_COORDS_B),
        ],
    }


@pytest.fixture()
def normalized_doc() -> dict:
    """A doc that already has trips_pct (simulating normalize output)."""
    fmt = list(STANDARD_NODE_FORMAT) + ["trips_pct"]
    return {
        "nodeFormat": fmt,
        "nodes": [
            _make_node(0, None, 100, 3, SAMPLE_COORDS_A) + [50.0],
            _make_node(1, 0, 200, 2, SAMPLE_COORDS_B) + [100.0],
            _make_node(2, 0, 50, 1, SAMPLE_COORDS_C) + [25.0],
        ],
    }


def write_json_file(path: Path, doc: dict) -> Path:
    """Helper: write a doc as JSON and return the path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False)
    return path
