# output/

GraphRAG pipeline output for **baseline (default prompts)** runs.

Contains Parquet files produced by `graphrag index`:

| File | Contents |
|---|---|
| `entities.parquet` | Extracted entities with descriptions and embeddings |
| `relationships.parquet` | Entity–entity relationships |
| `communities.parquet` | Hierarchical community membership |
| `community_reports.parquet` | AI-generated community summary reports |
| `documents.parquet` | Indexed source documents |
| `text_units.parquet` | Chunked text units |
| `covariates.parquet` | Extracted claims / covariates |
| `lancedb/` | Vector store used for local/global search |

> **Generated — do not commit.** All files in this directory are regenerated on each indexing run.
> Per-run isolated outputs are stored under `output/runs/{run_id}/`.
