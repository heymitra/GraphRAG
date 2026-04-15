#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

resolve_python_bin() {
    local candidates=()
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        candidates+=("${PYTHON_BIN}")
    fi
    candidates+=(
        "$PROJECT_ROOT/graphrag-env/bin/python"
        "$(command -v python3 || true)"
        "$(command -v python || true)"
    )

    for candidate in "${candidates[@]}"; do
        if [[ -n "$candidate" && -x "$candidate" ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    echo "Unable to locate a Python interpreter for GraphRAG." >&2
    exit 1
}

read_config_value() {
    local config_path="$1"
    local dotted_key="$2"
    "$PYTHON_BIN" - "$config_path" "$dotted_key" <<'PY'
import sys
from pathlib import Path

import yaml

config_path = Path(sys.argv[1])
keys = sys.argv[2].split(".")
data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
value = data
for key in keys:
    value = (value or {}).get(key)
print("" if value is None else value)
PY
}

resolve_project_path() {
    local path_value="$1"
    if [[ "$path_value" == /* ]]; then
        printf '%s\n' "$path_value"
    else
        printf '%s\n' "$PROJECT_ROOT/$path_value"
    fi
}

PYTHON_BIN="$(resolve_python_bin)"
CONFIG_FILE="${GRAPHRAG_CONFIG:-settings.yaml}"
if [[ "$CONFIG_FILE" != /* ]]; then
    CONFIG_FILE="$PROJECT_ROOT/$CONFIG_FILE"
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Config file not found: $CONFIG_FILE" >&2
    exit 1
fi

OUTPUT_DIR="${GRAPHRAG_OUTPUT_DIR:-$(read_config_value "$CONFIG_FILE" output.base_dir)}"
CACHE_DIR="${GRAPHRAG_CACHE_DIR:-$(read_config_value "$CONFIG_FILE" cache.base_dir)}"
OUTPUT_DIR="$(resolve_project_path "${OUTPUT_DIR:-output}")"
CACHE_DIR="$(resolve_project_path "${CACHE_DIR:-cache}")"
CLEAR_CACHE="${CLEAR_CACHE:-true}"
NEO4J_BROWSER_URL="${NEO4J_BROWSER_URL:-http://localhost:7475}"

echo "🚀 Starting GraphRAG update process..."
echo "🧭 Config: ${CONFIG_FILE#$PROJECT_ROOT/}"
echo "📦 Output: ${OUTPUT_DIR#$PROJECT_ROOT/}"
echo "🗂️ Cache: ${CACHE_DIR#$PROJECT_ROOT/}"

if [[ "$CLEAR_CACHE" == "true" ]]; then
    echo "🗑️ Clearing cache..."
    rm -rf "$CACHE_DIR"
else
    echo "♻️ Keeping cache (CLEAR_CACHE=false)"
fi

echo "📊 Re-indexing with GraphRAG..."
INDEX_CMD=(
    "$PYTHON_BIN"
    -m
    graphrag
    index
    --root
    "$PROJECT_ROOT"
    --config
    "$CONFIG_FILE"
)

if [[ -n "${GRAPHRAG_OUTPUT_DIR:-}" ]]; then
    INDEX_CMD+=(--output "$OUTPUT_DIR")
fi

"${INDEX_CMD[@]}"
echo "✅ GraphRAG indexing completed"

echo "🔄 Updating Neo4j database..."
OUTPUT_DIR="$OUTPUT_DIR" "$PYTHON_BIN" "$PROJECT_ROOT/import_neo4j.py"
echo "✅ Neo4j updated successfully"
echo "🌐 Open Neo4j Browser: $NEO4J_BROWSER_URL"
echo "📊 Or inspect the output in ${OUTPUT_DIR#$PROJECT_ROOT/}"
