# Auto Prompt Tuning

This repository supports Microsoft GraphRAG auto tuning on the **GraphRAG 2.7.1** config shape used by `settings.yaml` and `settings.auto.yaml`.

## What Auto Tuning Covers

In this repo's supported GraphRAG version, `prompt-tune` generates only three indexing prompts:

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
| `frontend/app.py` | Frontend that reads output/cache locations from the active config |

## End-to-End Workflow

### 1. Install the compatible version

```bash
python3 -m venv graphrag-env
source graphrag-env/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

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
CHUNK_SIZE="1200" \
OVERLAP="100" \
MIN_EXAMPLES_REQUIRED="2" \
DISCOVER_ENTITY_TYPES="false" \
./auto_tune.sh
```

### 4. Review the generated prompts

Check:

- `prompts_auto/extract_graph.txt` after generation
- `prompts_auto/summarize_descriptions.txt` after generation
- `prompts_auto/community_report_graph.txt` after generation

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

python -m graphrag query --root . --config settings.yaml      -m local  -q "What are the main entities and relationships?"
python -m graphrag query --root . --config settings.auto.yaml -m local  -q "What are the main entities and relationships?"

python -m graphrag query --root . --config settings.yaml      -m global -q "What themes dominate this corpus?"
python -m graphrag query --root . --config settings.auto.yaml -m global -q "What themes dominate this corpus?"
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
- Changing query prompts requires rerunning `graphrag query`, not reindexing.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `settings.auto.yaml` fails because `prompts_auto/` does not exist | Run `./auto_tune.sh` first |
| Frontend still shows baseline data | Launch it with `GRAPHRAG_CONFIG=settings.auto.yaml` |
| Tuned queries still look unchanged | Make sure you compare `settings.yaml` against `settings.auto.yaml`, not the same config twice |
| Claims quality still looks generic | That prompt is not auto-generated; tune `prompts/extract_claims.txt` manually |
