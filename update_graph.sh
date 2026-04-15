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

PYTHON_BIN="$(resolve_python_bin)"
CONFIG_FILE="${GRAPHRAG_CONFIG:-settings.yaml}"
CLEAR_CACHE="${CLEAR_CACHE:-true}"
NEO4J_BROWSER_URL="${NEO4J_BROWSER_URL:-http://localhost:7475}"

"$PYTHON_BIN" "$PROJECT_ROOT/graphrag_runtime.py" validate-prompts --config "$CONFIG_FILE"

STAGE_CMD=(
    "$PYTHON_BIN"
    "$PROJECT_ROOT/graphrag_runtime.py"
    stage
    --config
    "$CONFIG_FILE"
    --format
    shell
)

if [[ -n "${GRAPHRAG_OUTPUT_DIR:-}" ]]; then
    STAGE_CMD+=(--output-dir "$GRAPHRAG_OUTPUT_DIR")
fi

if [[ -n "${GRAPHRAG_CACHE_DIR:-}" ]]; then
    STAGE_CMD+=(--cache-dir "$GRAPHRAG_CACHE_DIR")
fi

eval "$("${STAGE_CMD[@]}")"

echo "Starting GraphRAG update process..."
echo "Config: ${CONFIG_PATH#$PROJECT_ROOT/}"
echo "Runtime root: ${RUNTIME_ROOT#$PROJECT_ROOT/}"
echo "Output: ${OUTPUT_DIR#$PROJECT_ROOT/}"
echo "Cache: ${CACHE_DIR#$PROJECT_ROOT/}"

if [[ "$CLEAR_CACHE" == "true" ]]; then
    echo "Clearing cache..."
    rm -rf "$CACHE_DIR"
else
    echo "Keeping cache (CLEAR_CACHE=false)"
fi

echo "Re-indexing with GraphRAG 3.x..."
"$PYTHON_BIN" -m graphrag index --root "$RUNTIME_ROOT"
echo "GraphRAG indexing completed"

echo "Updating Neo4j database..."
OUTPUT_DIR="$OUTPUT_DIR" "$PYTHON_BIN" "$PROJECT_ROOT/import_neo4j.py"
echo "Neo4j updated successfully"
echo "Open Neo4j Browser: $NEO4J_BROWSER_URL"
echo "Inspect the output in ${OUTPUT_DIR#$PROJECT_ROOT/}"
