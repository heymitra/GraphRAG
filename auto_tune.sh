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
CHUNK_SIZE="${CHUNK_SIZE:-3000}"
OVERLAP="${OVERLAP:-300}"
MIN_EXAMPLES_REQUIRED="${MIN_EXAMPLES_REQUIRED:-2}"
N_SUBSET_MAX="${N_SUBSET_MAX:-300}"
K="${K:-15}"
DISCOVER_ENTITY_TYPES="${DISCOVER_ENTITY_TYPES:-false}"

STAGE_CMD=(
    "$PYTHON_BIN"
    "$PROJECT_ROOT/graphrag_runtime.py"
    stage
    --config
    "$CONFIG_FILE"
    --for-prompt-tune
    --format
    shell
)
eval "$("${STAGE_CMD[@]}")"

LIMIT_INFO_CMD=(
    "$PYTHON_BIN"
    "$PROJECT_ROOT/graphrag_runtime.py"
    prompt-tune-limit
    --root
    "$RUNTIME_ROOT"
    --limit
    "$LIMIT"
    --chunk-size
    "$CHUNK_SIZE"
    --overlap
    "$OVERLAP"
    --format
    shell
)
eval "$("${LIMIT_INFO_CMD[@]}")"

if [[ "${AVAILABLE_CHUNKS:-0}" -le 0 ]]; then
    echo "Prompt tuning cannot run because the current input corpus produced no chunks." >&2
    echo "Check the extracted text files in input/ and the chunking settings." >&2
    exit 1
fi

if [[ "${EFFECTIVE_LIMIT}" != "${REQUESTED_LIMIT}" ]]; then
    echo "Requested LIMIT=$REQUESTED_LIMIT exceeds available chunks ($AVAILABLE_CHUNKS)." >&2
    echo "Capping prompt-tune limit to $EFFECTIVE_LIMIT for this run." >&2
fi

CMD=(
    "$PYTHON_BIN"
    -m
    graphrag
    prompt-tune
    --root
    "$RUNTIME_ROOT"
    --selection-method
    "$SELECTION_METHOD"
    --limit
    "$EFFECTIVE_LIMIT"
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
    "$PROJECT_ROOT/prompts_auto"
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
echo "Config: ${CONFIG_PATH#$PROJECT_ROOT/}"
echo "Runtime root: ${RUNTIME_ROOT#$PROJECT_ROOT/}"
echo "Prompt staging: prompts_auto/ paths fall back to prompts/ until tuned prompts are generated."
echo "Prompt output: prompts_auto/"
echo "Selection method: $SELECTION_METHOD"
echo "Prompt-tune chunks available: $AVAILABLE_CHUNKS"
echo "Prompt-tune limit: $EFFECTIVE_LIMIT"

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
echo "       ./query_graph.sh -m local \"What are the main entities and relationships?\""
echo "       GRAPHRAG_CONFIG=settings.auto.yaml ./query_graph.sh -m local \"What are the main entities and relationships?\""
