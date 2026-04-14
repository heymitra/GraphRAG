# Search Strategies

GraphRAG supports four query strategies. Each is optimised for a different question type, operates on different artifacts, and has different latency and cost characteristics.

---

## Strategy Comparison

| Strategy | Best for | Primary artifacts | LLM calls | Relative speed |
|----------|----------|------------------|-----------|----------------|
| **Local** | Specific entities, facts, relationships | Entities, relationships, text units, community reports | 1 | Fast |
| **Global** | Broad themes, corpus-level patterns, dataset summaries | Community reports (all levels) | _N_×map + 1 reduce | Medium |
| **DRIFT** | Complex analysis requiring both depth and breadth | Community reports → local entity context | Multiple iterations | Slow |
| **Basic** | Simple lookups, latency-sensitive queries | Text unit embeddings only | 1 | Fastest |

**CLI:**
```bash
python3 -m graphrag query --method local  --query "Who is John Doe?"
python3 -m graphrag query --method global --query "What are the main themes in this corpus?"
python3 -m graphrag query --method drift  --query "Analyse the relationship between X and Y"
python3 -m graphrag query --method basic  --query "Find documents about Z"
```

---

## Local Search

Local search is **entity-centric**. It starts by finding entities most relevant to the query, then assembles a rich context window from those entities and their surrounding graph neighbourhood.

### Flow

```
User query
    │
    ▼
Embed query → ANN search over entity description vectors
    │
    ▼
Top-K most relevant entities
    │
    ▼
Expand context:
  ─ entity descriptions and types
  ─ relationships to/from those entities
  ─ community reports for the entities' communities
  ─ text units that mention those entities
    │
    ▼
Assemble structured context tables → LLM (local_search_system_prompt.txt) → Answer
```

### Context assembled for the LLM

The LLM receives structured markdown tables:

```
Entities
id | name       | type | description
1  | ACME CORP  | ORG  | A technology company...

Relationships
id | source    | target   | description           | weight
3  | ACME CORP | JOHN DOE | John is CEO of Acme   | 9

Text Units
id | text
7  | "Acme Corp announced..."

Community Reports
id | title             | summary
2  | Acme Corp Network | ...
```

Citations in the LLM response reference these IDs: `[Data: Entities (1); Relationships (3)]`.

### When to use local search

- "What does Acme Corp do?"
- "What is the relationship between Person X and Organisation Y?"
- "List all known claims about Entity Z"
- "Who are the key people in this project?"

---

## Global Search

Global search is **corpus-level**. It reasons over all community reports using a map-reduce pattern, producing answers to questions that require understanding broad themes or patterns across the entire document set.

### Flow

```
User query
    │
    ▼
Retrieve ALL community reports (filtered by level)
    │
    ├── Shard into groups
    │       └── MAP phase: each shard → LLM → scored key-points JSON
    │
    ▼
Merge and rank all key-points
    │
    ▼
REDUCE phase: LLM synthesises top key-points → final markdown answer
```

### Map phase

Each shard of community reports is sent to the LLM independently with `global_search_map_system_prompt.txt`. The LLM acts as a "virtual analyst" and returns:

```json
{
  "points": [
    {
      "description": "Acme Corp dominates enterprise observability [Data: Reports (5)]",
      "score": 85
    }
  ]
}
```

### Reduce phase

All key-points from all map shards are merged, ranked by score, and sent to the LLM with `global_search_reduce_system_prompt.txt`, which synthesises them into a single coherent markdown response.

### Community level selection

The `level` parameter controls which community reports are included. In current GraphRAG, lower levels are broader and higher levels are more fine-grained. The CLI default is `--community-level 2`, and the query layer includes reports up to that level (`level <= community_level`) so you can cap the maximum refinement depth.

### When to use global search

- "What are the key topics discussed in these documents?"
- "Summarise the main actors and their roles"
- "What are the most significant findings or events?"
- "What patterns or themes emerge across the corpus?"

---

## DRIFT Search

DRIFT (**D**ynamic **R**easoning and **I**nference with **F**lexible **T**raversal) is a hybrid strategy that combines the breadth of global search with the depth of local search through iterative refinement.

### Flow

```
User query
    │
    ▼
Global-style initial pass:
  community reports → broad answer + sub-queries + confidence score
    │
    ├── Sub-query 1 → local entity context → partial answer + score
    ├── Sub-query 2 → local entity context → partial answer + score
    └── Sub-query N → local entity context → partial answer + score
    │
    ▼
Reduce: merge all partial answers → final response
```

### Iteration and stopping

Each DRIFT iteration produces a **score** (0–100) representing how well the current partial answer addresses the original question. The pipeline uses this score to decide when further iteration adds diminishing returns.

The `drift_search_system_prompt.txt` is designed to produce both an answer component and follow-up sub-queries in a single structured output.

### When to use DRIFT

- Complex analytical questions requiring both an overview and specific evidence
- Research-style exploration where the best sub-questions are not known in advance
- Questions where a global summary alone is insufficient but pure local search misses the big picture

---

## Basic Search

Basic search is equivalent to **classic vector RAG** with no graph reasoning. It is fast, predictable, and useful as a baseline.

### Flow

```
User query → embed → ANN search over text_unit embeddings → top-K chunks → LLM → Answer
```

### When to use basic search

- Simple factual lookup with a clear single answer
- Latency-sensitive applications
- Baseline comparison against graph-augmented strategies
- Queries where entity relationships are irrelevant

---

## Context Assembly Details

For local and DRIFT search, context is assembled from multiple sources and formatted as markdown tables. The `max_input_length` and token budget parameters control how much context fits in a single LLM call.

### Token budget management

If more entities or relationships are retrieved than fit within the token budget, GraphRAG trims the lowest-weight items:
- Relationships are ranked by `weight`
- Text units are ranked by relevance score
- Community reports are included by rank

```yaml
community_reports:
  max_input_length: 8000    # tokens allocated for community report context
```

### Citation format

All LLM answers should include inline citations referencing the structured IDs from the context tables:

```
[Data: Entities (1, 3); Relationships (7, 12); Text Units (5)]
```

This citation format is enforced by the system prompts and allows answers to be traced back through the provenance chain to source documents.
