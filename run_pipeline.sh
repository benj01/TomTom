#!/usr/bin/env bash
#
# run_pipeline.sh – Clean-run the full TomTom processing pipeline.
#
# Steps:
#   1. Validate raw/ (pre-flight checks)
#   2. Clean output/ and shapefiles/ (fresh reprocess)
#   3. Normalize trips  (raw/ → output/)
#   4. Convert to shapefiles (output/ → shapefiles/)
#
# Usage:
#   ./run_pipeline.sh                 # default directories
#   ./run_pipeline.sh --skip-clean    # keep existing output/ and shapefiles/
#   ./run_pipeline.sh --raw ./myraw   # custom raw directory

set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RAW_DIR="${SCRIPT_DIR}/raw"
OUTPUT_DIR="${SCRIPT_DIR}/output"
SHAPEFILES_DIR="${SCRIPT_DIR}/shapefiles"
SKIP_CLEAN=false
ROUND=2
PRETTY=""

# ── Parse arguments ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --raw)       RAW_DIR="$2";        shift 2 ;;
        --output)    OUTPUT_DIR="$2";      shift 2 ;;
        --shapefiles) SHAPEFILES_DIR="$2"; shift 2 ;;
        --skip-clean) SKIP_CLEAN=true;     shift   ;;
        --round)     ROUND="$2";           shift 2 ;;
        --pretty)    PRETTY="--pretty";    shift   ;;
        -h|--help)
            echo "Usage: $0 [--raw DIR] [--output DIR] [--shapefiles DIR]"
            echo "          [--skip-clean] [--round N] [--pretty]"
            exit 0
            ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

echo "=== TomTom Pipeline ==="
echo "  Raw:        ${RAW_DIR}"
echo "  Output:     ${OUTPUT_DIR}"
echo "  Shapefiles: ${SHAPEFILES_DIR}"
echo ""

# ── Step 1: Validate ────────────────────────────────────────────────
echo "--- Step 1: Validating raw files ---"
python3 "${SCRIPT_DIR}/validate_raw.py" \
    --raw_dir "${RAW_DIR}" \
    --output_dir "${OUTPUT_DIR}"

# validate_raw exits 1 on errors; set -e will stop the pipeline here.
echo ""

# ── Step 2: Clean (optional) ────────────────────────────────────────
if [ "${SKIP_CLEAN}" = false ]; then
    echo "--- Step 2: Cleaning output directories ---"
    if [ -d "${OUTPUT_DIR}" ]; then
        rm -rf "${OUTPUT_DIR}"
        echo "  Removed ${OUTPUT_DIR}"
    fi
    if [ -d "${SHAPEFILES_DIR}" ]; then
        rm -rf "${SHAPEFILES_DIR}"
        echo "  Removed ${SHAPEFILES_DIR}"
    fi
    echo ""
else
    echo "--- Step 2: Skipped (--skip-clean) ---"
    echo ""
fi

# ── Step 3: Normalize ───────────────────────────────────────────────
echo "--- Step 3: Normalizing trips ---"
python3 "${SCRIPT_DIR}/normalize_trips.py" \
    --input_dir "${RAW_DIR}" \
    --output_dir "${OUTPUT_DIR}" \
    --round "${ROUND}" \
    ${PRETTY}
echo ""

# ── Step 4: Convert to shapefiles ──────────────────────────────────
echo "--- Step 4: Converting to shapefiles (merge mode) ---"
python3 "${SCRIPT_DIR}/json_to_shapefile.py" \
    --input_dir "${OUTPUT_DIR}" \
    --output_dir "${SHAPEFILES_DIR}" \
    --merge
echo ""

echo "=== Pipeline complete ==="
