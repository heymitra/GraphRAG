# GraphRAG Documentation

Technical documentation for the Microsoft GraphRAG pipeline in this repository, including the Neo4j import layer and the 3.x config/runtime wrappers used by this project.

## Contents

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System overview and how GraphRAG differs from plain vector RAG |
| [Indexing Pipeline](indexing_pipeline.md) | Step-by-step pipeline from documents to graph outputs |
| [Data Model](data_model.md) | Schema for the parquet outputs, LanceDB, embeddings, and provenance |
| [Search Strategies](search.md) | Local, Global, DRIFT, and Basic search behavior |
| [Auto Prompt Tuning](auto_tuning.md) | How this repo runs GraphRAG auto tuning on 3.0.6 |
| [Prompts Reference](prompts.md) | Every prompt file used by the repo |
| [Configuration Reference](configuration.md) | Annotated `settings.yaml` and `settings.auto.yaml` |
| [Neo4j Schema](neo4j.md) | Node labels, relationship types, indexes, and Cypher examples |

## Quick Start

### Full baseline rebuild

```bash
source graphrag-env/bin/activate
./update_graph.sh
```

### Auto-tuned run

```bash
source graphrag-env/bin/activate
DOMAIN="your corpus domain" ./auto_tune.sh
GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh
GRAPHRAG_CONFIG=settings.auto.yaml python3 frontend/app.py
```

### Query

```bash
./query_graph.sh -m local  "Who is X?"
./query_graph.sh -m global "What are the main themes?"
GRAPHRAG_CONFIG=settings.auto.yaml ./query_graph.sh -m local "Who is X?"
```

### Raw GraphRAG 3.x CLI

```bash
source graphrag-env/bin/activate
eval "$(python graphrag_runtime.py stage --config settings.yaml --format shell)"
python3 -m graphrag index --root "$RUNTIME_ROOT"
python3 -m graphrag query --root "$RUNTIME_ROOT" --data "$OUTPUT_DIR" -m local "Who is X?"
```

## Key File Locations

| Path | Purpose |
|------|---------|
| `settings.yaml` | Baseline GraphRAG 3.x config |
| `settings.auto.yaml` | Tuned GraphRAG config |
| `graphrag_runtime.py` | Stages selected configs into `.graphrag-runtime/` |
| `prompts/` | Baseline prompt templates |
| `prompts_auto/` | Auto-generated indexing prompts |
| `input/` | Source `.txt` documents |
| `output/*.parquet` | Baseline persisted knowledge model |
| `output_auto/*.parquet` | Tuned persisted knowledge model |
| `cache/` and `cache_auto/` | LLM response caches |
| `import_neo4j.py` | Loads GraphRAG output into Neo4j |
| `frontend/app.py` | Web UI for uploads and inspection |
