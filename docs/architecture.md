# Architecture Overview

## What GraphRAG Is

**GraphRAG** (Graph Retrieval-Augmented Generation) is a Microsoft Research system that transforms unstructured text into a **hierarchical knowledge graph** and uses that graph to ground LLM answers with richer, more structured context than plain embedding-similarity RAG.

The key idea: instead of retrieving raw text chunks at query time, GraphRAG pre-computes a canonicalized knowledge graph and a hierarchy of community summaries during indexing. Queries then reason over these structured artifacts rather than over raw document text.

Published paper: [_From Local to Global: A Graph RAG Approach to Query-Focused Summarization_](https://arxiv.org/abs/2404.16130) (Edge et al., 2024)

---

## System Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          INDEXING PIPELINE                              │
│                                                                         │
│  Input Docs                                                             │
│      │                                                                  │
│      ▼                                                                  │
│  Chunking  ──────────────────────────────────────────────────────────  │
│      │                                                                  │
│      ▼  (parallel across chunks)                                        │
│  Entity & Relationship Extraction (LLM)   ◄── gleaning passes          │
│  Claim / Covariate Extraction (LLM)       ◄── gleaning passes          │
│      │                                                                  │
│      ▼                                                                  │
│  Cross-chunk Merge (same title+type → canonical entity/relationship)   │
│      │                                                                  │
│      ▼                                                                  │
│  Description Summarisation (LLM, per entity/rel with multiple descs)   │
│      │                                                                  │
│      ▼                                                                  │
│  Community Detection (hierarchical Leiden algorithm)                   │
│      │                                                                  │
│      ▼                                                                  │
│  Community Reports (LLM, per community)                                │
│      │                                                                  │
│      ▼                                                                  │
│  Text Embeddings + Graph Embeddings + UMAP                             │
│      │                                                                  │
│      ▼                                                                  │
│  Parquet tables  ·  LanceDB vector store  ·  GraphML snapshot          │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
              ┌─────────────────────┼──────────────────────┐
              ▼                     ▼                      ▼
       Local Search          Global Search          DRIFT / Basic
    (entity-centric)      (community-level)          (hybrid)
```

---

## Core Concepts

| Concept | Description |
|---------|-------------|
| **TextUnit** | A fixed-size chunk of source text (~3 000 tokens). The atomic unit of extraction and retrieval. |
| **Entity** | A named thing extracted by the LLM — person, organisation, geography, event, product, or technology. Represented as a canonical node in the knowledge graph. |
| **Relationship** | A directed, weighted edge between two entities, carrying a natural-language description and a strength score (1–10). |
| **Claim / Covariate** | A fact or assertion about an entity, with explicit truth status (`TRUE` / `FALSE` / `SUSPECTED`), optional time bounds, and verbatim source text. Stored separately from relationships because they carry richer epistemic metadata. |
| **Community** | A cluster of densely connected entities produced by hierarchical Leiden community detection — not invented by a prompt. Communities exist at multiple levels of granularity. |
| **Community Report** | An LLM-generated analytical summary of a community. The primary retrieval unit for global reasoning. |
| **Embedding** | Dense vector representations used for similarity retrieval — both semantic (text embeddings) and structural (graph/node2vec embeddings). |

---

## Why GraphRAG vs. Plain Vector RAG

Plain vector RAG retrieves text chunks by embedding similarity. It cannot reason about **relationships** or **themes** that span many documents, because that information is never made explicit — it is diffuse across hundreds of chunks.

GraphRAG addresses this through four structural properties:

### 1. Graph structure makes relationships first-class citizens

Entities and their connections are extracted and stored explicitly. The LLM does not have to infer "what is the relationship between A and B?" from raw text at query time — the answer is pre-computed in `relationships.parquet`.

### 2. Community hierarchy enables multi-scale reasoning

Leiden clustering groups related entities at multiple levels of granularity:
- Fine-grained communities (level 0) represent tight local clusters, e.g. a company and its immediate leadership.
- Coarser parent communities (levels 1, 2, …) represent broader ecosystems, e.g. an entire industry.

This hierarchy lets search navigate from broad overview to specific detail, or operate at the right granularity for a given question.

### 3. Pre-computed community reports make broad questions cheap

For a question like "What are the main themes in this corpus?", plain RAG would need to scan and synthesise thousands of chunks at query time. GraphRAG instead reasons over pre-computed community reports — LLM-generated summaries created once during indexing — making whole-corpus questions fast and consistent.

### 4. Multiple search strategies for different question types

| Question type | Optimal strategy |
|---------------|-----------------|
| Facts about a specific entity | Local search |
| Broad themes and corpus-level patterns | Global search |
| Complex analysis requiring both breadth and depth | DRIFT |
| Simple lookup, latency-sensitive | Basic (pure vector) |

---

## Repository Layout

```
graphRAG/
├── settings.yaml          # All pipeline configuration
├── prompts/               # Every LLM prompt — editable
│   ├── extract_graph.txt
│   ├── summarize_descriptions.txt
│   ├── extract_claims.txt
│   ├── community_report_graph.txt
│   ├── community_report_text.txt
│   ├── local_search_system_prompt.txt
│   ├── global_search_map_system_prompt.txt
│   ├── global_search_reduce_system_prompt.txt
│   ├── drift_search_system_prompt.txt
│   └── basic_search_system_prompt.txt
├── input/                 # Source .txt files (one per document)
├── output/                # Parquet tables + LanceDB + GraphML
│   └── lancedb/           # Embedded vector store
├── cache/                 # LLM response cache (speeds re-runs)
├── logs/                  # Pipeline run statistics
├── import_neo4j.py        # Loads Parquet outputs into Neo4j
├── extract_pdf.py         # PDF → plain text helper
└── update_graph.sh        # Full rebuild in one command
```

---

## Two-Phase Design

The most important architectural property to understand is that GraphRAG builds the knowledge model in **two distinct phases**:

**Phase 1 — Chunk-local extraction (parallel)**  
Each TextUnit is processed independently and concurrently. The LLM extracts entities, relationships, and claims from each chunk without knowledge of other chunks. This is fast and horizontally scalable.

**Phase 2 — Global consolidation (sequential)**  
Chunk-local extractions are merged into a canonical graph. Duplicate entities and relationships (same name+type across chunks) are unified. Descriptions are summarised into single canonical representations. Communities are detected from the merged graph structure. Reports are generated per community.

This two-phase design means:
- Extraction scales with corpus size (more chunks → more parallel LLM calls, not slower serial processing).
- The final knowledge model is globally consistent — no duplicate entity rows, no inconsistent descriptions.
- LLM cache is chunk-level, so re-runs on unchanged documents are free.
