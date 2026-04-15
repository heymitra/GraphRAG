# GraphRAG Neo4j Integration

Extract knowledge graphs from documents with [Microsoft GraphRAG](https://github.com/microsoft/graphrag), inspect them in Neo4j, and compare baseline prompts against auto-tuned prompts without overwriting your main pipeline output.

## Supported Version

This repository is pinned to **GraphRAG 3.0.6**.

- `requirements.txt` installs the current 3.x release used by this repo.
- `settings.yaml` and `settings.auto.yaml` are already migrated to the 3.x config schema.
- GraphRAG 3.x no longer accepts `--config`, so this repo stages the selected config into `.graphrag-runtime/` before running `index`, `query`, or `prompt-tune`.

If you previously installed GraphRAG 2.x in the same virtual environment, recreating the virtual environment is safer than doing an in-place upgrade.

## Features

- PDF ingestion with `extract_pdf.py`
- GraphRAG indexing for entities, relationships, claims, and communities
- Neo4j import for GraphRAG parquet output
- Flask frontend for uploads, pipeline logs, and graph exploration
- Auto prompt tuning with isolated tuned prompts, cache, logs, and output
- Manual prompt tuning for claims and query prompts
- Baseline and tuned querying through `query_graph.sh`

## Project Structure

```text
├── auto_tune.sh          # Generate auto-tuned indexing prompts into prompts_auto/
├── query_graph.sh        # Query the active GraphRAG config without hand-building a runtime root
├── graphrag_runtime.py   # Shared helper that stages configs into .graphrag-runtime/
├── settings.yaml         # Baseline GraphRAG 3.x config
├── settings.auto.yaml    # Tuned GraphRAG config using prompts_auto/ and output_auto/
├── prompts/              # Baseline prompt files
├── input/                # Source text files
├── output/               # Baseline GraphRAG output
├── output_auto/          # Tuned GraphRAG output (generated, git-ignored)
├── import_neo4j.py       # Neo4j import script
├── update_graph.sh       # Re-index + Neo4j import using the active config
├── frontend/app.py       # Web UI; respects GRAPHRAG_CONFIG
└── docs/                 # Deeper technical docs
```

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv graphrag-env
source graphrag-env/bin/activate
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure your OpenAI key

Create `.env` in the project root:

```dotenv
GRAPHRAG_API_KEY=your_openai_api_key
GRAPHRAG_API_BASE=https://api.openai.com/v1
```

### 4. Start Neo4j

```bash
docker run -d \
  --name graphrag-neo4j \
  -p 7475:7474 -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/graphrag123 \
  neo4j:latest
```

- Browser: `http://localhost:7475`
- Bolt: `bolt://localhost:7688`

## Baseline Usage

### Rebuild the baseline graph

```bash
source graphrag-env/bin/activate
./update_graph.sh
```

The script reads the active config, stages a 3.x-compatible runtime root, optionally clears the matching cache directory, runs GraphRAG indexing, and imports the matching output directory into Neo4j.

### Start the frontend

```bash
source graphrag-env/bin/activate
python frontend/app.py
```

Open `http://localhost:8501`.

### Run baseline queries

```bash
source graphrag-env/bin/activate
./query_graph.sh -m local  "What are the main entities and relationships?"
./query_graph.sh -m global "What are the main themes in this corpus?"
./query_graph.sh -m drift  "How are the main actors connected?"
./query_graph.sh -m basic  "Find documents about topic X"
```

## Auto Prompt Tuning

GraphRAG auto tuning in this repo is for **indexing prompts**. In GraphRAG 3.0.6 it generates:

- `prompts_auto/extract_graph.txt`
- `prompts_auto/summarize_descriptions.txt`
- `prompts_auto/community_report_graph.txt`

It does **not** generate:

- `extract_claims.txt`
- `community_report_text.txt`
- local/global/drift/basic query prompts

Those remain manual edits.

### 1. Generate tuned prompts

```bash
source graphrag-env/bin/activate
DOMAIN="your corpus domain" ./auto_tune.sh
```

`DOMAIN` is recommended but not required. If you omit it, GraphRAG will infer a domain from your input corpus.

Useful environment variables:

```bash
DOMAIN="biotech research" \
LANGUAGE="English" \
SELECTION_METHOD="random" \
LIMIT="15" \
CHUNK_SIZE="3000" \
OVERLAP="300" \
DISCOVER_ENTITY_TYPES="false" \
./auto_tune.sh
```

`auto_tune.sh` writes prompts to `prompts_auto/` and keeps your baseline prompts untouched.

### 2. Run the tuned pipeline

```bash
source graphrag-env/bin/activate
GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh
```

`settings.auto.yaml` is already configured to:

- read the same `input/`
- use `prompts_auto/` for the auto-generated indexing prompts
- write artifacts to `output_auto/`
- use separate cache and logs in `cache_auto/` and `logs_auto/`

### 3. Launch the frontend against tuned output

```bash
source graphrag-env/bin/activate
GRAPHRAG_CONFIG=settings.auto.yaml python frontend/app.py
```

The frontend derives its output and cache directories from the active config, so the tuned UI reads `output_auto/` automatically.

### 4. Compare baseline vs tuned results

Compare the same question against both configs:

```bash
source graphrag-env/bin/activate

./query_graph.sh -m local "What are the main entities and relationships?"
GRAPHRAG_CONFIG=settings.auto.yaml ./query_graph.sh -m local "What are the main entities and relationships?"

./query_graph.sh -m global "What themes dominate this corpus?"
GRAPHRAG_CONFIG=settings.auto.yaml ./query_graph.sh -m global "What themes dominate this corpus?"
```

When comparing, look at:

- entity type quality
- relationship recall and phrasing
- community report titles and summaries
- answer grounding and citation quality
- whether the tuned graph produces better Neo4j structure for your domain

## Manual Prompt Tuning

Use manual tuning for anything auto tuning does not cover.

### Indexing prompts that require re-indexing

- `prompts/extract_graph.txt`
- `prompts/summarize_descriptions.txt`
- `prompts/extract_claims.txt`
- `prompts/community_report_graph.txt`
- `prompts/community_report_text.txt`

After changing indexing prompts, re-run the relevant pipeline:

```bash
./update_graph.sh
# or
GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh
```

### Query prompts that do not require re-indexing

- `prompts/local_search_system_prompt.txt`
- `prompts/global_search_map_system_prompt.txt`
- `prompts/global_search_reduce_system_prompt.txt`
- `prompts/global_search_knowledge_system_prompt.txt`
- `prompts/drift_search_system_prompt.txt`
- `prompts/drift_reduce_prompt.txt`
- `prompts/basic_search_system_prompt.txt`

After changing query prompts, rerun `./query_graph.sh`.

## Adding Documents

### Convert a PDF to text

```bash
source graphrag-env/bin/activate
python extract_pdf.py
```

### Add a `.txt` file directly

Drop one text file per source document into `input/`, then rerun the baseline or tuned pipeline.

## Advanced CLI Usage

If you want to call the raw GraphRAG 3.x CLI directly, stage the desired config first:

```bash
source graphrag-env/bin/activate
eval "$(python graphrag_runtime.py stage --config settings.auto.yaml --format shell)"
python -m graphrag query --root "$RUNTIME_ROOT" --data "$OUTPUT_DIR" -m local "What changed after tuning?"
```

`query_graph.sh`, `update_graph.sh`, and `auto_tune.sh` already do this for you.

## Documentation

- [Overview](docs/README.md)
- [Auto Prompt Tuning](docs/auto_tuning.md)
- [Prompt Reference](docs/prompts.md)
- [Configuration Reference](docs/configuration.md)
- [Search Strategies](docs/search.md)
- [Indexing Pipeline](docs/indexing_pipeline.md)
