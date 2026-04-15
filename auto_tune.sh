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

if [[ "$CONFIG_FILE" != /* ]]; then
    CONFIG_FILE="$PROJECT_ROOT/$CONFIG_FILE"
fi

if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Config file not found: $CONFIG_FILE" >&2
    exit 1
fi

shopt -s nullglob
input_files=("$PROJECT_ROOT"/input/*.txt)
shopt -u nullglob
if (( ${#input_files[@]} == 0 )); then
    echo "No input .txt files found in input/. Add corpus text files before running auto tuning." >&2
    exit 1
fi

DOMAIN="${DOMAIN:-}"
LANGUAGE="${LANGUAGE:-English}"
SELECTION_METHOD="${SELECTION_METHOD:-random}"
LIMIT="${LIMIT:-15}"
MAX_TOKENS="${MAX_TOKENS:-2000}"
CHUNK_SIZE="${CHUNK_SIZE:-1200}"
OVERLAP="${OVERLAP:-100}"
MIN_EXAMPLES_REQUIRED="${MIN_EXAMPLES_REQUIRED:-2}"
N_SUBSET_MAX="${N_SUBSET_MAX:-300}"
K="${K:-15}"
DISCOVER_ENTITY_TYPES="${DISCOVER_ENTITY_TYPES:-false}"

CMD=(
    "$PYTHON_BIN"
    -m
    graphrag
    prompt-tune
    --root
    "$PROJECT_ROOT"
    --config
    "$CONFIG_FILE"
    --selection-method
    "$SELECTION_METHOD"
    --limit
    "$LIMIT"
    --max-tokens
    "$MAX_TOKENS"
    --chunk-size
    "$CHUNK_SIZE"
    --overlap
    "$OVERLAP"
    --min-examples-required
    "$MIN_EXAMPLES_REQUIRED"
    --n-subset-max
    "$N_SUBSET_MAX"
    --k
    "$K"
    --language
    "$LANGUAGE"
    --output
    prompts_auto
)

if [[ -n "$DOMAIN" ]]; then
    CMD+=(--domain "$DOMAIN")
fi

if [[ "$DISCOVER_ENTITY_TYPES" == "true" ]]; then
    CMD+=(--discover-entity-types)
else
    CMD+=(--no-discover-entity-types)
fi

echo "Generating auto-tuned prompts..."
echo "  Config: ${CONFIG_FILE#$PROJECT_ROOT/}"
echo "  Output: prompts_auto/"
echo "  Selection method: $SELECTION_METHOD"

"${CMD[@]}"

echo
echo "Auto-tuned prompts written to prompts_auto/."
echo "Next steps:"
echo "  1. Review prompts_auto/extract_graph.txt, prompts_auto/summarize_descriptions.txt, and prompts_auto/community_report_graph.txt"
echo "  2. Run the tuned pipeline:"
echo "       GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh"
echo "  3. Launch the frontend against the tuned output:"
echo "       GRAPHRAG_CONFIG=settings.auto.yaml $PYTHON_BIN frontend/app.py"
echo "  4. Compare answers with the baseline:"
echo "       $PYTHON_BIN -m graphrag query --root . --config settings.yaml -m local -q \"What are the main entities and relationships?\""
echo "       $PYTHON_BIN -m graphrag query --root . --config settings.auto.yaml -m local -q \"What are the main entities and relationships?\""
