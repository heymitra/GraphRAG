# Data Model & Persistence

All pipeline outputs land in `output/` as **Apache Parquet** tables, a **LanceDB** vector database directory, and optional snapshot artifacts. This document describes every schema, the LanceDB structure, and the provenance model.

---

## Parquet Tables

### `documents.parquet`

One row per source `.txt` file.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `title` | string | Source filename |
| `text` | string | Full document text |
| `human_readable_id` | int | Sequential display ID |
| `creation_date` | string | ISO-8601 date |
| `metadata` | dict | Extra metadata |

---

### `text_units.parquet`

One row per text chunk.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `text` | string | Chunk text |
| `n_tokens` | int | Token count |
| `human_readable_id` | int | Sequential display ID |
| `document_ids` | list[str] | Parent document IDs |
| `entity_ids` | list[str] | Canonical entities extracted from this chunk |
| `relationship_ids` | list[str] | Canonical relationships evidenced by this chunk |
| `covariate_ids` | list[str] | Claims extracted from this chunk |

---

### `entities.parquet`

One row per canonical entity. This table is the result of cross-chunk merge and description summarisation — it contains no duplicates.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `title` | string | Canonical entity name (the merge key) |
| `type` | string | `organization`, `person`, `geo`, `event`, `product`, `technology` |
| `description` | string | Single canonical description — result of summarising all chunk-level raw descriptions |
| `human_readable_id` | int | Sequential display ID |
| `frequency` | int | Number of chunks that mention this entity |
| `degree` | int | Number of relationships this entity participates in |
| `x`, `y` | float | UMAP 2D coordinates from graph-structural embeddings; for visualisation only |

**Merge key:** `title + type`. Two chunk-level extractions with the same name and type are collapsed into one canonical entity row.

---

### `relationships.parquet`

One row per canonical relationship. Also deduplicated across chunks.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `source` | string | Source entity name |
| `target` | string | Target entity name |
| `description` | string | Canonical summarised description |
| `weight` | float | Relationship strength (1–10, from extraction prompt) |
| `combined_degree` | int | `source.degree + target.degree` |
| `human_readable_id` | int | Sequential display ID |
| `text_unit_ids` | list[str] | Chunks that provide evidence for this relationship |

**Merge key:** `source + target`. Multiple chunk-level extractions of the same source-target pair are merged, and their descriptions are summarised into one.

---

### `covariates.parquet` — Claims

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `covariate_type` | string | Covariate category (typically `"claim"`) |
| `type` | string | Claim sub-type |
| `description` | string | Full explanation of the claim |
| `status` | string | `TRUE`, `FALSE`, or `SUSPECTED` |
| `source_text` | string | Verbatim supporting text from the chunk |
| `subject_id` | string | Subject entity name |
| `object_id` | string | Object entity name, or `NONE` |
| `start_date` | string | ISO-8601 or `NONE` |
| `end_date` | string | ISO-8601 or `NONE` |
| `text_unit_id` | string | Source TextUnit ID |
| `human_readable_id` | int | Sequential display ID |

Claims are not merged or deduplicated across chunks in the same way as entities and relationships.

---

### `communities.parquet`

One row per community at every hierarchy level.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `community` | int | Community number (used for hierarchy joins) |
| `level` | int | `0` = broadest/root split; higher = finer child communities created by recursive splitting |
| `title` | string | Community label |
| `size` | int | Number of member entities |
| `period` | string | Temporal scope if inferred from content |
| `parent` | int | Parent community number; `-1` = root |
| `children` | list[int] | Child community numbers |
| `entity_ids` | list[str] | Member entity IDs |
| `relationship_ids` | list[str] | Internal relationship IDs |
| `text_unit_ids` | list[str] | Supporting TextUnit IDs |
| `human_readable_id` | int | Sequential display ID |

---

### `community_reports.parquet`

One row per community report. A report is generated for each community by an LLM call that receives the community's entities and relationships as context.

| Column | Type | Description |
|--------|------|-------------|
| `id` | UUID string | Primary key |
| `community` | int | Community number this report describes |
| `level` | int | Hierarchy level of the community |
| `title` | string | Report title |
| `summary` | string | Executive summary paragraph |
| `full_content` | string | Full human-readable analytical report |
| `full_content_json` | string | JSON-serialised structured version of the report |
| `rank` | float | Importance / impact score (0–10) |
| `rating_explanation` | string | One-sentence rationale for the score |
| `findings` | list[dict] | Analytical findings as `{summary, explanation}` items |
| `period` | string | Temporal scope |
| `size` | int | Community size |
| `human_readable_id` | int | Sequential display ID |

---

## Embedding Files

Three sets of embeddings are stored as Parquet files alongside the main tables:

| File | Embedded field | Model |
|------|---------------|-------|
| `embeddings.entity.description.parquet` | `Entity.description` | `text-embedding-3-small` |
| `embeddings.text_unit.text.parquet` | `TextUnit.text` | `text-embedding-3-small` |
| `embeddings.community.full_content.parquet` | `CommunityReport.full_content` | `text-embedding-3-small` |

Each file contains `id` and a dense vector per row.

---

## LanceDB (`output/lancedb/`)

LanceDB is the embedded vector store used at query time. It mirrors the embedding Parquet files in a format optimised for approximate nearest-neighbour (ANN) retrieval.

```
output/lancedb/
└── default/
    ├── entity_description/
    ├── text_unit_text/
    └── community_full_content/
```

Each table is queried by embedding the user's query with the same model used during indexing, then finding the nearest vectors in the relevant table.

---

## `graph.graphml`

Standard GraphML export of the finalized entity-relationship graph. This is an **interchange and inspection artifact** — it contains the same entity and relationship data as `entities.parquet` and `relationships.parquet` but in a format compatible with external graph tools (Gephi, Cytoscape, yEd).

It is **not** used by GraphRAG's runtime query methods.

---

## Cache (`cache/`)

LLM responses are cached keyed on their input hash. This means:
- Re-running with identical inputs and prompts reuses prior LLM results (no API cost).
- Changing a prompt file or `entity_types` requires clearing the cache (`rm -rf cache/`), because the input hash changes.
- `update_graph.sh` clears the cache before a full rebuild.

---

## Key Design Patterns

### Canonicalization

The final `entities.parquet` and `relationships.parquet` are **canonical**: one row per logical entity/relationship, regardless of how many chunks mentioned it. The `description` field is already post-summarisation. This is what makes GraphRAG's outputs deterministic and non-redundant.

### ID types

| ID field | Nature | Used for |
|----------|--------|---------|
| `id` | UUID, globally unique | All joins, foreign keys |
| `human_readable_id` | Sequential integer | Display, compact references |
| `community` | Integer | Hierarchy joins between communities and reports |

### List fields

Many columns are arrays: `entity_ids`, `relationship_ids`, `text_unit_ids`, `children`, `covariate_ids`. These are the mechanism that preserves provenance and cross-level hierarchy links throughout the data model.

### Provenance chain

Every artifact can be traced back to source text through a consistent chain:

```
Entity / Relationship
  → text_unit_ids
    → TextUnit.text
      → document_ids
        → Document.text

Claim
  → text_unit_id
    → TextUnit.text
      → document_ids
        → Document.text

CommunityReport
  → community (Community record)
    → entity_ids / relationship_ids / text_unit_ids
      → Entity / Relationship / TextUnit
        → Document
```

This provenance chain is what allows GraphRAG to produce grounded answers with `[Data: Entities (id); Relationships (id)]` citations rather than free-form generated text.
