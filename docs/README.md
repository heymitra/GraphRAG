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
rm -rf cache/
graphrag index
python3 import_neo4j.py
```

### Query

```bash
graphrag query --method local  --query "Who is X?"
graphrag query --method global --query "What are the main themes?"
graphrag query --method drift  --query "Analyse the relationship between X and Y"
graphrag query --method basic  --query "Find documents about Z"
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
