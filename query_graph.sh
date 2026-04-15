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

eval "$("${STAGE_CMD[@]}")"

exec "$PYTHON_BIN" -m graphrag query --root "$RUNTIME_ROOT" --data "$OUTPUT_DIR" "$@"
