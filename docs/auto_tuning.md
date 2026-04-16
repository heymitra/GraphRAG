# Auto Prompt Tuning

This repository supports Microsoft GraphRAG auto tuning on **GraphRAG 3.0.6**.

For a code-level explanation of upstream GraphRAG prompt tuning behavior, what changes between baseline and auto-tuned indexing, why there is no dedicated canonicalization stage, and which flags are worth testing, see [GraphRAG Auto-Tuning Deep Dive](graphrag_auto_tuning_deep_dive.md).

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

`auto_tune.sh` also stages a prompt-tune-safe runtime. If the selected config points at `prompts_auto/` before those files exist, the staging layer temporarily falls back to the matching baseline prompt files in `prompts/` so prompt generation can complete.

The wrapper now also caps the effective prompt-tune `LIMIT` to the number of available chunks in the current corpus. This works around an upstream GraphRAG 3.0.6 bug where `prompt-tune` crashes if `limit` is larger than the chunk population.

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

When the frontend is launched with `GRAPHRAG_CONFIG=settings.auto.yaml`, `Auto-tuned prompts` becomes the startup dataset. The same UI still lets you switch back to `Default prompts` for comparison.

When you upload with the `Auto-tuned prompts` mode selected, the frontend does this automatically:

1. the uploaded PDF is extracted into `input/`
2. `auto_tune.sh` runs against the current `input/` corpus
3. `prompts_auto/` is regenerated
4. tuned indexing runs into `output_auto/`

This is the right mode if you expect tuned prompts to be derived from the newly uploaded document before the graph is rebuilt.

The frontend now separates extraction QA from graph publishing:

- the results workspace strip shows which prompt source and pipeline path are active
- `Current Prompt Set` previews the live prompt files for the selected dataset or next upload path
- the upload modal can pass per-upload auto-tune flags such as `DOMAIN`, `SELECTION_METHOD`, `LIMIT`, `CHUNK_SIZE`, and `DISCOVER_ENTITY_TYPES`
- the `Documents` modal shows indexed document metadata, explorer-only inclusion checkboxes, and the exact prompt snapshot recorded for a document's successful indexing run
- Neo4j sync is manual from `Documents -> Sync Neo4j`
- document inclusion checkboxes do not change prompt tuning, indexing, or the Neo4j import payload

Frontend uploads now persist prompt provenance in `prompt_history/`. For auto-tuned runs this matters because the tuned prompts are corpus-derived: `Documents -> Inspect exact prompts` lets you inspect the generated prompt snapshot that was actually used for that document, even after `prompts_auto/` changes later.

If you want to reuse existing tuned prompts instead of regenerating them on every upload:

```bash
source graphrag-env/bin/activate
AUTO_TUNE_ON_UPLOAD=false GRAPHRAG_CONFIG=settings.auto.yaml python frontend/app.py
```

That opt-out mode restores the stricter behavior where `prompts_auto/` must already exist.

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
| `KeyError: 'tuple_delimiter'` or prompt validation fails | One or more prompt files still use legacy GraphRAG 2.x placeholders. Replace them with GraphRAG 3.x prompt files or rerun `./auto_tune.sh` to regenerate `prompts_auto/` |
| The frontend keeps showing baseline data after a tuned upload | Switch the top-bar dataset selector to `Auto-tuned prompts`, or upload with that mode selected so the UI switches there automatically when the run finishes |
| The frontend should start in tuned mode after a restart | Launch it with `GRAPHRAG_CONFIG=settings.auto.yaml` to make `Auto-tuned prompts` the startup default |
| Neo4j did not change after a tuned upload | Frontend uploads no longer import Neo4j automatically. Open `Documents` and click `Sync Neo4j` after you inspect the tuned output |
| Tuned queries still look unchanged | Make sure one run uses `settings.yaml` and the other uses `settings.auto.yaml` |
| The explorer shows fewer rows than the parquet counts suggest | The `Documents` modal checkboxes filter what the frontend displays. Re-include the documents you want visible |
| Claims quality still looks generic | That prompt is not auto-generated; tune `prompts/extract_claims.txt` manually |
| `generate_text_embeddings` fails with `multiple of the list_size` | `text-embedding-3-small` needs `vector_store.vector_size: 1536`. This repo now validates that early and resets the local LanceDB output before rebuilds |
| A reused old venv has strange dependency conflicts | Recreate `graphrag-env` and reinstall from `requirements.txt` |
| Tuned uploads are slower than baseline uploads | That is expected because `prompt-tune` runs before indexing when `AUTO_TUNE_ON_UPLOAD` is enabled |
