# Indexing Pipeline

The pipeline is triggered with `python -m graphrag index` (or via `update_graph.sh`). Each step reads from earlier artifacts and writes new ones to `output/`.

## Overview

```
Step 0   Document Ingestion    → documents.parquet
Step 1   Text Chunking         → text_units.parquet
Step 2   Entity & Rel Extract  → (provisional per-chunk subgraphs)    ← LLM, parallel
Step 3   NLP Extraction        → (auxiliary graph signals)             ← non-LLM
Step 4   Description Summaris. → entities.parquet, relationships.parquet ← LLM, post-merge
Step 5   Claim Extraction      → covariates.parquet                   ← LLM, parallel
Step 6   Community Detection   → communities.parquet                  ← Leiden algorithm
Step 7   Community Reports     → community_reports.parquet            ← LLM, per community
Step 8   Embeddings            → embeddings.*.parquet, LanceDB
Step 9   UMAP                  → Entity.x, Entity.y
Step 10  Snapshots             → graph.graphml, embedding files
```

**Cost formula** for a corpus with _N_ chunks and _C_ communities:
- Steps 2+4: ~`N × (1 + max_gleanings)` graph-extraction LLM calls + summarisation calls for merged entities with multiple descriptions
- Step 5: ~`N × (1 + max_gleanings)` claim-extraction LLM calls
- Step 7: ~`C` community-report LLM calls

LLM responses are cached by input hash (`cache/`), so re-runs on unchanged inputs and prompts reuse prior results.

---

## Step 0 — Document Ingestion

**Input:** `.txt` files in `input/`  
**Output:** `documents.parquet`

Each file becomes one `Document` record with `id` (UUID), `title` (filename), `text` (full content), `creation_date`, and `metadata`. This is primarily a bookkeeping and provenance step. GraphRAG does not reason over whole documents directly after this point; it reasons over `TextUnit`s.

---

## Step 1 — Text Chunking

**Output:** `text_units.parquet`

```yaml
chunks:
  size: 3000
  overlap: 300
  group_by_columns: [id]
```

Each `TextUnit` records: `id`, `text`, `n_tokens`, `human_readable_id`, `document_ids`.

### Why chunking exists

LLMs and embedding models operate on bounded context windows. Large documents must be split into smaller units before GraphRAG can extract entities, relationships, and claims.

### Why overlap exists

`overlap: 300` makes adjacent chunks share ~300 tokens. This mitigates boundary effects — an entity mention that spans the end of one chunk and the beginning of the next will be fully visible in at least one of the two extraction passes.

### Chunk size trade-offs

| Smaller chunks | Larger chunks |
|----------------|---------------|
| More granular extraction | Fewer LLM calls |
| More LLM calls | More context per call |
| Better boundary coverage with overlap | Risk of missing fine-grained entities near boundaries |

### Important clarification

GraphRAG does **not** present multiple adjacent chunks to the LLM as a single extended window. Extraction is still **one chunk at a time**. Cross-chunk consistency is achieved later through merging and summarisation, not multi-chunk prompting.

---

## Step 2 — Entity & Relationship Extraction

**Prompt:** `prompts/extract_graph.txt`  
**Called per:** each TextUnit  
**Model:** `default_chat_model` (`gpt-4o-mini`)  
**Parallelism:** concurrent across chunks, bounded by `concurrent_requests: 25`

### LLM input

```
Entity_types: organization, person, geo, event, product, technology
Text: <chunk text>
```

### LLM output format

```
("entity"<|>ENTITY_NAME<|>TYPE<|>description)
<|>
("relationship"<|>SOURCE<|>TARGET<|>description<|>strength 1-10)
<COMPLETE>
```

### What this step produces

For each chunk, the LLM produces a small **local subgraph**: entity nodes visible in that chunk and relationship edges between them. At this stage, extraction is entirely local to a chunk — no deduplication or cross-chunk merging yet.

### Parallel execution

The pipeline processes multiple chunks concurrently. The runtime pattern is:

1. Chunks A, B, C, … are dispatched concurrently to the LLM.
2. Each chunk produces its own provisional entity/relationship output independently.
3. Duplicate entities across chunks are resolved in Step 4's merge phase.

### Gleaning (recall improvement)

`max_gleanings: 2` allows up to **2 additional passes on the same chunk** if the pipeline believes the first pass may have missed entities or relationships.

The gleaning prompt is approximately:

> "MANY entities were missed in the last extraction. Add the missing entities and relationships now."

Gleaning improves recall — especially for weaker or less salient entities near the end of a chunk — at the cost of additional LLM calls. Gleaning passes are **sequential within one chunk** because each pass must see the previous output.

**Concurrency model:**
- Across chunks → parallel
- Within one chunk (gleaning passes) → sequential

With `max_gleanings: 2`, each chunk requires up to 3 LLM calls for graph extraction.

---

## Step 3 — NLP-Based Extraction (Optional)

```yaml
extract_graph_nlp:
  text_analyzer:
    extractor_type: regex_english
  async_mode: threaded
```

This is a **non-LLM** extraction path. Depending on the configured analyzer (`regex_english`, `syntactic_parser`, `cfg`), it applies deterministic or rule-based text analysis to surface graph-like signals without calling the chat model.

It exists to provide lower-cost extraction, deterministic behaviour, or augmentation for specialised GraphRAG variants. In this repository the primary graph comes from Step 2's LLM-driven extraction; Step 3 should be treated as an auxiliary or experimental capability.

---

## Step 4 — Cross-Chunk Merge & Description Summarisation

**Output:** `entities.parquet`, `relationships.parquet`  
**Prompt:** `prompts/summarize_descriptions.txt`  
**Called per:** entity or relationship that accumulated more than one description

### Duplicate resolution rules

After parallel extraction, multiple chunks may have independently produced the same entity or relationship. GraphRAG resolves duplicates using these merge keys:

- **Entities:** same `title` + same `type` → one canonical entity
- **Relationships:** same `source` + same `target` → one canonical relationship

After merging, a canonical entity may hold multiple raw descriptions gathered from different chunks.

### Description summarisation

Example of a merged entity with multiple descriptions:

| Source chunk | Raw description |
|---|---|
| A | "Acme Corp is an enterprise software vendor" |
| B | "Acme Corp sells observability products" |
| C | "Acme Corp has offices in Berlin and partners with Contoso" |

The summarisation LLM call receives:

```
Entity: ACME CORP
Description list: [desc_A, desc_B, desc_C]
Max length: 500
```

And returns a single coherent third-person paragraph that merges and reconciles all descriptions.

### What the final parquet looks like

The final `entities.parquet` and `relationships.parquet` contain **one row per canonical entity/relationship** with a single `description` field. There are no duplicate rows and no multi-description lists in the output.

---

## Step 5 — Claim / Covariate Extraction

**Prompt:** `prompts/extract_claims.txt`  
**Called per:** each TextUnit  
**Output:** `covariates.parquet`

```yaml
extract_claims:
  enabled: true
  max_gleanings: 1
  description: "Any claims or facts that could be relevant to information discovery."
```

### LLM input

```
Entity specification: organization, person, geo, event, product, technology
Claim description: Any claims or facts that could be relevant to information discovery.
Text: <chunk text>
```

### Output format

```
(SUBJECT<|>OBJECT<|>CLAIM_TYPE<|>STATUS<|>START_DATE<|>END_DATE<|>DESCRIPTION<|>SOURCE_TEXT)
```

`STATUS` must be one of: `TRUE`, `FALSE`, `SUSPECTED`.

### Claims vs. relationships

A relationship expresses a structural connection between two entities. A claim adds:
- Explicit truth status (`TRUE` / `FALSE` / `SUSPECTED`)
- Optional time bounds (`start_date`, `end_date`)
- Verbatim supporting text (`source_text`)
- Explicit subject and object roles

This is why GraphRAG keeps claims in a separate artifact (`covariates.parquet`) rather than collapsing them into standard graph edges.

### Claim-to-entity linking

The claim extractor emits subject and object as **names** (strings). The import pipeline later links these to canonical entity nodes by matching those names against `Entity.name`. In Neo4j:

```
Claim -[:ABOUT_SUBJECT]-> Entity   (matched by subject_id = Entity.name)
Claim -[:ABOUT_OBJECT]->  Entity   (matched by object_id  = Entity.name)
Claim -[:EXTRACTED_FROM]-> TextUnit (matched by text_unit_id)
```

Linking quality depends on naming consistency. If a claim uses a surface form that differs from the canonical entity title (e.g. "Acme" vs. "Acme Corp"), the link may be incomplete.

### Parallelism

Same model as Step 2: concurrent across chunks, sequential gleaning within a chunk. With `max_gleanings: 1`, each chunk requires up to 2 LLM calls for claim extraction.

---

## Step 6 — Community Detection

**Algorithm:** Hierarchical Leiden  
**Output:** `communities.parquet`

```yaml
cluster_graph:
  max_cluster_size: 10
```

### What a community is

A community is a cluster of entities that are more densely connected to each other than to the rest of the graph. Communities are **derived entirely from graph structure** — the algorithm analyses the entity-relationship graph and partitions it; no LLM is involved in this step.

Examples of natural communities:
- A company, its founders, subsidiaries, and key products
- An event, the people who organised it, the organisations involved, and the venues
- A research topic, the researchers, institutions, and technologies associated with it

### Hierarchical Leiden

The Leiden algorithm produces a **recursive hierarchy** of communities:

- `level = 0` — finest granularity; small, tightly connected local clusters
- `level = 1` — parent clusters that group level-0 communities
- `level = 2` — broader still
- Higher levels — increasingly coarse-grained, corpus-level views

This hierarchy supports reasoning at different scales: drill into a level-0 community for detail, or examine a level-2 community for an overview of an entire domain.

### `max_cluster_size`

This parameter controls the recursive splitting threshold. When a candidate community exceeds this size, the algorithm splits it further.

- Lower value → more, smaller communities (more focused, easier to summarise)
- Higher value → fewer, larger communities (broader scope, harder to summarise cleanly)

### Community record structure

Each row in `communities.parquet` is a **cluster index object** that links together:
- `entity_ids` — member entities
- `relationship_ids` — internal relationships
- `text_unit_ids` — source text chunks
- `parent` — parent community number (`-1` = root)
- `children` — child community numbers
- `level`, `size`, `period`

---

## Step 7 — Community Reports

**Called per:** each community  
**Prompt:** `prompts/community_report_graph.txt` (or `community_report_text.txt`)  
**Output:** `community_reports.parquet`

```yaml
community_reports:
  max_length: 2000
  max_input_length: 8000
```

### LLM input

For each community, GraphRAG assembles a structured evidence block:

```
Entities
id, entity, description
5, ACME CORP, A technology company...

Relationships
id, source, target, description
37, ACME CORP, JOHN DOE, John Doe is CEO of Acme Corp
```

### LLM output (JSON)

```json
{
  "title": "Acme Corp Executive Network",
  "summary": "...",
  "rating": 7.5,
  "rating_explanation": "...",
  "findings": [
    {
      "summary": "Acme Corp dominates enterprise observability",
      "explanation": "... [Data: Entities (5); Relationships (37)]"
    }
  ]
}
```

### Community report fields

| Field | Meaning |
|-------|---------|
| `community` | Community number this report describes |
| `level` | Hierarchy level — determines whether global search uses this report at broad or fine granularity |
| `title` | Short human-readable label for display |
| `summary` | Executive summary — used in global search context |
| `full_content` | Full analytical report — rich retrieval and UI payload |
| `full_content_json` | Machine-readable JSON version |
| `rank` | Impact / importance score (0–10) — used to prioritise reports in global search |
| `findings` | Ordered list of `{summary, explanation}` items with `[Data: ...]` citations |
| `size` | Number of entities in the community |

### Why community reports are central

Community reports are not cosmetic summaries. They are one of the primary **retrieval artifacts** in GraphRAG:

- **Global search** reasons over them directly (map-reduce over all reports)
- **DRIFT search** starts from them before drilling into local evidence
- Frontends can surface them as interpretable summaries of graph regions
- They make whole-corpus questions tractable without scanning every chunk at query time

---

## Step 8 — Embeddings

```yaml
embed_text:
  model_id: default_embedding_model    # text-embedding-3-small

embed_graph:
  enabled: true
```

### Text embeddings

Three fields are embedded and stored in both Parquet files and LanceDB:

| Parquet file | Embedded field | Used by |
|---|---|---|
| `embeddings.entity.description.parquet` | `Entity.description` | Local search, DRIFT |
| `embeddings.text_unit.text.parquet` | `TextUnit.text` | Local search, Basic search |
| `embeddings.community.full_content.parquet` | `CommunityReport.full_content` | Global search, DRIFT |

### Graph embeddings (node2vec)

`embed_graph: enabled: true` computes **structural embeddings** for entity nodes using a graph embedding algorithm (node2vec). These capture where a node sits in the graph topology — which communities it belongs to, how central it is, which other nodes it is adjacent to.

These structural vectors are distinct from semantic text embeddings. They reflect graph structure, not semantic meaning.

### LanceDB

All retrieval-ready vectors are stored in `output/lancedb/default/` with tables for `entity_description`, `text_unit_text`, and `community_full_content`. LanceDB is the embedded vector store used at query time.

---

## Step 9 — UMAP Layout

```yaml
umap:
  enabled: true
```

UMAP reduces the high-dimensional graph embeddings (from Step 8) to 2D coordinates stored as `Entity.x` and `Entity.y`.

### Interpretation

- Entities **close together** in (x, y) have similar graph neighbourhoods or community membership.
- Entities **far apart** are structurally dissimilar.
- The axes themselves carry **no semantic meaning**. Only relative position matters.
- These are **not** geographic coordinates, semantic scales, or importance rankings.

UMAP coordinates are primarily a **visualisation aid** — for frontend graph displays, debugging cluster quality, and spotting hubs and outliers. They are not used in any of the standard search strategies.

**Prerequisite:** `embed_graph: enabled: true` must be set; UMAP operates on the graph embeddings.

---

## Step 10 — Snapshots

```yaml
snapshots:
  graphml: true
  embeddings: true
```

### `graph.graphml`

A standard GraphML export of the finalized entity-relationship graph, written to `output/graph.graphml`. Useful for:
- Opening in **Gephi**, **Cytoscape**, or **yEd** for alternative layouts and visual exploration
- Running external graph algorithms
- Debugging cluster quality and graph connectivity
- Sharing the graph with tools that do not understand Parquet

This file is an **export / inspection artifact**. It is not the primary artifact used by any of GraphRAG's query methods at runtime.

### Embedding snapshots (`snapshots.embeddings: true`)

Persists the embedding arrays as files in addition to storing them in LanceDB. Useful for:
- Offline analysis in notebooks
- Reproducibility and version control of embeddings
- Debugging retrieval behaviour without going through the vector store API

---

## Concurrency and Caching Summary

| Dimension | Behaviour |
|-----------|-----------|
| Across chunks (Step 2, 5) | Parallel — `concurrent_requests: 25` |
| Within a chunk — gleaning | Sequential — each pass depends on the previous |
| Across communities (Step 7) | Parallel |
| LLM response cache | Keyed on input hash; cleared by `rm -rf cache/` |
| Re-run cost | Zero for unchanged inputs/prompts; full cost for new/changed inputs |

Clearing the cache is necessary after changing any prompt file or `entity_types`, because the cache key includes the prompt content.
