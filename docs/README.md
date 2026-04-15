# GraphRAG Documentation

Technical documentation for the Microsoft GraphRAG pipeline in this repository, including the Neo4j import layer and graph visualization extensions.

---

## Contents

| Document | Description |
|----------|-------------|
| [Architecture](architecture.md) | System overview, core concepts, and how GraphRAG differs from plain vector RAG |
| [Indexing Pipeline](indexing_pipeline.md) | Step-by-step pipeline: chunking, extraction, merging, communities, embeddings, and snapshots — including all concurrency and implementation details |
| [Data Model](data_model.md) | Schema for every Parquet table, LanceDB, embeddings, GraphML, and provenance chains |
| [Search Strategies](search.md) | Local, Global, DRIFT, and Basic search — flows, context assembly, token budgets, and when to use each |
| [Auto Prompt Tuning](auto_tuning.md) | How this repo enables GraphRAG auto tuning, what files it generates, and how to compare baseline vs tuned runs |
| [Prompts Reference](prompts.md) | Every LLM prompt explained: variables, input/output formats, and customisation guide |
| [Configuration Reference](configuration.md) | Annotated `settings.yaml` with trade-off notes for every significant setting |
| [Neo4j Schema](neo4j.md) | Node labels, relationship types, indexes, and Cypher query cookbook |

---

## Quick Start

### Full rebuild

```bash
./update_graph.sh
```

### Manual steps

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
python3 -m graphrag query --root . --config settings.yaml -m local  -q "Who is X?"
python3 -m graphrag query --root . --config settings.yaml -m global -q "What are the main themes?"
python3 -m graphrag query --root . --config settings.auto.yaml -m local -q "Who is X?"
```

### Manual indexing steps

```bash
source graphrag-env/bin/activate
rm -rf cache/
python3 -m graphrag index --root . --config settings.yaml
python3 import_neo4j.py
```

---

## Key File Locations

| Path | Purpose |
|------|---------|
| `settings.yaml` | All pipeline configuration |
| `prompts/` | LLM prompt templates (indexing and query) |
| `input/` | Source `.txt` documents |
| `output/*.parquet` | Canonical persisted knowledge model |
| `output/lancedb/` | Vector store for retrieval |
| `output/graph.graphml` | Graph snapshot for Gephi / Cytoscape |
| `cache/` | LLM response cache |
| `import_neo4j.py` | Loads all Parquet outputs into Neo4j |
| `extract_pdf.py` | PDF-to-text helper |

---

## Pipeline Mental Model

```
Documents
  └─► TextUnits (chunks)
        └─► Chunk-local extraction (parallel)
              └─► Cross-chunk merge + description summarisation
                    └─► Canonical graph (entities + relationships + claims)
                          └─► Community detection (Leiden)
                                └─► Community reports (LLM, per community)
                                      └─► Embeddings + UMAP + GraphML snapshots
```

The central insight of GraphRAG is that retrieval happens over **pre-computed, structured summaries** of the graph — not over raw text chunks alone. This makes broad, multi-document reasoning tractable at query time.
