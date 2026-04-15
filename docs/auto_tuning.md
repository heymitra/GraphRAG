# Auto Prompt Tuning

This repository supports Microsoft GraphRAG auto tuning on **GraphRAG 3.0.6**.

## What Auto Tuning Covers

In GraphRAG 3.0.6, `prompt-tune` generates only three indexing prompts:

- `prompts_auto/extract_graph.txt`
- `prompts_auto/summarize_descriptions.txt`
- `prompts_auto/community_report_graph.txt`

It does not generate:

- `prompts/extract_claims.txt`
- `prompts/community_report_text.txt`
- query prompts under `prompts/*search*`

That split is why this repo ships a dedicated `settings.auto.yaml`: the tuned config swaps in only the prompt files that GraphRAG auto tuning actually creates, while the remaining prompts continue to come from `prompts/`.

## Files Involved

| File | Role |
|------|------|
| `auto_tune.sh` | Wrapper around `python -m graphrag prompt-tune` |
| `settings.auto.yaml` | Tuned config using `prompts_auto/`, `output_auto/`, `cache_auto/`, and `logs_auto/` |
| `update_graph.sh` | Rebuild script that respects the active config |
| `query_graph.sh` | Query wrapper for the active config |
| `graphrag_runtime.py` | Stages the active config into `.graphrag-runtime/` for GraphRAG 3.x |
| `frontend/app.py` | Frontend that reads output and cache locations from the active config |

## End-to-End Workflow

### 1. Install the pinned version

```bash
python3 -m venv graphrag-env
source graphrag-env/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you are upgrading an old 2.x environment, rebuilding the virtual environment is recommended.

### 2. Prepare your input data

Place `.txt` files in `input/`. Auto tuning samples from the same dataset you plan to index.

### 3. Generate tuned prompts

Minimal run:

```bash
source graphrag-env/bin/activate
DOMAIN="your corpus domain" ./auto_tune.sh
```

More explicit run:

```bash
source graphrag-env/bin/activate
DOMAIN="biomedical literature" \
LANGUAGE="English" \
SELECTION_METHOD="random" \
LIMIT="15" \
MAX_TOKENS="2000" \
CHUNK_SIZE="3000" \
OVERLAP="300" \
MIN_EXAMPLES_REQUIRED="2" \
DISCOVER_ENTITY_TYPES="false" \
./auto_tune.sh
```

The defaults in `auto_tune.sh` intentionally match this repo's 3.x chunking settings.

### 4. Review the generated prompts

Check:

- `prompts_auto/extract_graph.txt`
- `prompts_auto/summarize_descriptions.txt`
- `prompts_auto/community_report_graph.txt`

Things worth reviewing:

- domain vocabulary in entity types and examples
- whether extracted relationship wording matches your documents
- whether community report titles and ratings are useful for your search tasks

### 5. Index the tuned graph

```bash
source graphrag-env/bin/activate
GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh
```

That writes to:

- `output_auto/`
- `cache_auto/`
- `logs_auto/`

Your baseline `output/` remains untouched.

### 6. Run the frontend on tuned output

```bash
source graphrag-env/bin/activate
GRAPHRAG_CONFIG=settings.auto.yaml python frontend/app.py
```

### 7. Compare baseline vs tuned query answers

```bash
source graphrag-env/bin/activate

./query_graph.sh -m local "What are the main entities and relationships?"
GRAPHRAG_CONFIG=settings.auto.yaml ./query_graph.sh -m local "What are the main entities and relationships?"

./query_graph.sh -m global "What themes dominate this corpus?"
GRAPHRAG_CONFIG=settings.auto.yaml ./query_graph.sh -m global "What themes dominate this corpus?"
```

## Manual Tuning After Auto Tuning

Auto tuning is usually the first pass, not the last one.

### Tune these manually even after auto tuning

- `prompts/extract_claims.txt`
- `prompts/community_report_text.txt`
- `prompts/local_search_system_prompt.txt`
- `prompts/global_search_map_system_prompt.txt`
- `prompts/global_search_reduce_system_prompt.txt`
- `prompts/global_search_knowledge_system_prompt.txt`
- `prompts/drift_search_system_prompt.txt`
- `prompts/drift_reduce_prompt.txt`
- `prompts/basic_search_system_prompt.txt`

### Reindexing rule

- Changing indexing prompts requires reindexing.
- Changing query prompts requires rerunning `./query_graph.sh`, not reindexing.

## Raw GraphRAG 3.x Commands

The repo wrappers stage the right config automatically, but if you need the upstream CLI directly:

```bash
source graphrag-env/bin/activate
eval "$(python graphrag_runtime.py stage --config settings.auto.yaml --format shell)"
python -m graphrag prompt-tune --root "$RUNTIME_ROOT" --output "$PWD/prompts_auto"
python -m graphrag index --root "$RUNTIME_ROOT"
python -m graphrag query --root "$RUNTIME_ROOT" --data "$OUTPUT_DIR" -m local "What changed after tuning?"
```

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `settings.auto.yaml` fails because `prompts_auto/` does not exist | Run `./auto_tune.sh` first |
| Frontend still shows baseline data | Launch it with `GRAPHRAG_CONFIG=settings.auto.yaml` |
| Tuned queries still look unchanged | Make sure one run uses `settings.yaml` and the other uses `settings.auto.yaml` |
| Claims quality still looks generic | That prompt is not auto-generated; tune `prompts/extract_claims.txt` manually |
| A reused old venv has strange dependency conflicts | Recreate `graphrag-env` and reinstall from `requirements.txt` |
