# Prompts Reference

All prompts live in `prompts/` and are referenced from `settings.yaml`. Prompts are plain text files — edit them freely to adapt entity types, output formats, language, or analytical focus.

Most prompts use `{variable}` placeholders that GraphRAG fills at runtime. In `graphrag==3.0.6`, the extraction prompts use literal delimiter tokens in the prompt body:

- tuple delimiter: `<|>`
- record delimiter: `##`
- completion delimiter: `<|COMPLETE|>`

Legacy 2.x placeholders like `{tuple_delimiter}`, `{record_delimiter}`, and `{completion_delimiter}` will fail under GraphRAG 3.x.

`./auto_tune.sh` generates tuned indexing prompts into `prompts_auto/` and the companion `settings.auto.yaml` points only the supported auto-generated files at that directory. In this repo's `graphrag==3.0.6` setup, auto tuning generates:

- `extract_graph.txt`
- `summarize_descriptions.txt`
- `community_report_graph.txt`

It does **not** generate `extract_claims.txt`, `community_report_text.txt`, or any query-time prompts. Those remain manual.

---

## Indexing Prompts

### `extract_graph.txt` — Entity & Relationship Extraction

**Pipeline step:** Step 2 — called once per TextUnit (plus gleaning passes)  
**Model:** `default_completion_model`

**Variables injected:**

| Variable | Source | Example value |
|----------|--------|---------------|
| `{entity_types}` | `settings.yaml → extract_graph.entity_types` | `organization,person,geo,event,product,technology` |
| `{input_text}` | TextUnit text | Raw chunk content |

**Task:**
1. Extract all entities of the configured types and emit `("entity"|name|type|description)` tuples.
2. Extract all relationships between those entities and emit `("relationship"|source|target|description|strength)` tuples.
3. If `max_gleanings > 0`, GraphRAG re-prompts with: _"MANY entities were missed in the last extraction. Add the missing entities and relationships now."_

**Output example:**
```
("entity"<|>ACME CORP<|>ORGANIZATION<|>A software company building enterprise tools)
##
("relationship"<|>ACME CORP<|>JOHN DOE<|>John Doe is the CEO of Acme Corp<|>9)
<|COMPLETE|>
```

**Customisation notes:**
- To add a new entity type, add it to `entity_types` in `settings.yaml` **and** update the few-shot examples in `extract_graph.txt` to include instances of that type.
- Strength values (1–10) map to `relationship.weight` in the final parquet.

---

### `summarize_descriptions.txt` — Description Summarisation

**Pipeline step:** Step 4 — called per entity or relationship that accumulated more than one description across chunks  
**Model:** `default_completion_model`

**Variables injected:**

| Variable | Source | Example value |
|----------|--------|---------------|
| `{entity_name}` | Canonical entity title | `ACME CORP` |
| `{description_list}` | All raw descriptions collected from chunks | `["desc from chunk A", "desc from chunk B", ...]` |
| `{max_length}` | `settings.yaml → summarize_descriptions.max_length` | `500` |

**Task:** Merge all descriptions into a single coherent third-person paragraph. Resolve any contradictions or redundancies.

**Output:** A single string. This becomes the canonical `description` field in `entities.parquet` or `relationships.parquet`.

---

### `extract_claims.txt` — Claim / Covariate Extraction

**Pipeline step:** Step 5 — called once per TextUnit (plus gleaning passes)  
**Model:** `default_completion_model`

**Variables injected:**

| Variable | Source | Example value |
|----------|--------|---------------|
| `{entity_specs}` | Entity types or specific entity names | `organization, person, geo, event, product, technology` |
| `{claim_description}` | `settings.yaml → extract_claims.description` | `"Any claims or facts that could be relevant to information discovery."` |
| `{input_text}` | TextUnit text | Raw chunk content |

**Output format:**
```
(SUBJECT<|>OBJECT<|>CLAIM_TYPE<|>STATUS<|>START_DATE<|>END_DATE<|>DESCRIPTION<|>SOURCE_TEXT)
```

`STATUS` must be `TRUE`, `FALSE`, or `SUSPECTED`.  
`OBJECT`, `START_DATE`, `END_DATE` may be `NONE`.

---

### `community_report_graph.txt` — Community Report (Graph Context)

**Pipeline step:** Step 7 — called per community  
**Model:** `default_completion_model`

**Variables injected:**

| Variable | Source |
|----------|--------|
| `{input_text}` | Formatted tables of member entities and internal relationships |
| `{max_report_length}` | `settings.yaml → community_reports.max_length` (default `2000`) |

**Input text structure:**
```
Entities
id,entity,description
5,ACME CORP,A technology company...

Relationships
id,source,target,description
37,ACME CORP,JOHN DOE,John Doe is CEO
```

**Required JSON output:**
```json
{
  "title": "Acme Corp Executive Network",
  "summary": "...",
  "rating": 7.5,
  "rating_explanation": "...",
  "findings": [
    {
      "summary": "Short headline",
      "explanation": "Grounded explanation [Data: Entities (5); Relationships (37)]"
    }
  ]
}
```

**Customisation notes:**
- Add or remove fields from the JSON schema to extend the report structure.
- Adjust the prompt's analytical instructions to focus on domain-specific dimensions (e.g., risk, sentiment, temporal patterns).
- The `rating` field is used to rank reports in global search — customise the scoring rubric to match your corpus.

---

### `community_report_text.txt` — Community Report (Text Context)

Same structure as `community_report_graph.txt` but `{input_text}` contains raw text excerpts instead of structured entity/relationship tables. Used in configurations where text-based evidence is preferred over the structured graph representation.

---

## Query-Time Prompts

These prompts are not called during indexing. They are invoked at query time by the respective search strategy.

---

### `local_search_system_prompt.txt` — Local Search

**Variables injected:**

| Variable | Content |
|----------|---------|
| `{context_data}` | Structured tables of entities, relationships, text units, and community reports retrieved for the query |
| `{response_type}` | Target format, e.g. `"multiple paragraphs"` |

**Behaviour:** Grounds the answer in the retrieved context. Citations use `[Data: Entities (id); Relationships (id)]` format. The LLM should not hallucinate facts outside the provided context.

---

### `global_search_map_system_prompt.txt` — Global Search, Map Phase

**Called per:** shard of community reports during the map phase of global search.

Each shard is analysed independently. The prompt instructs the LLM to act as a "virtual analyst" and output a scored list of key points relevant to the query:

```json
{
  "points": [
    {
      "description": "Key finding [Data: Reports (3)]",
      "score": 80
    }
  ]
}
```

Scores drive ranking during the reduce phase.

---

### `global_search_reduce_system_prompt.txt` — Global Search, Reduce Phase

**Called once:** receives the ranked key-points from all map-phase analysts.

Synthesises the input into a single coherent markdown response. The "virtual analyst" framing from the map phase is not surfaced in the final answer.

---

### `global_search_knowledge_system_prompt.txt` — Global Search, World Knowledge

Supplements global search with general world knowledge when the community reports do not provide sufficient context to answer the query. Acts as a fallback layer.

---

### `drift_search_system_prompt.txt` — DRIFT Search

**Variables injected:**

| Variable | Content |
|----------|---------|
| `{context_data}` | Mixed community report and entity data for the current iteration |

Produces both a partial answer component and a set of follow-up sub-queries with confidence scores. The scores drive the iteration stopping criterion.

---

### `drift_reduce_prompt.txt` — DRIFT Reduce

Merges multiple partial answers from DRIFT iterations into a single coherent final response.

---

### `basic_search_system_prompt.txt` — Basic Search

Answers questions from retrieved text chunks with no graph context. Equivalent to a classic RAG prompt.

---

### `question_gen_system_prompt.txt` — Question Generation

This prompt file exists in the GraphRAG prompt pack for question generation workflows. In the pinned `graphrag==3.0.6` CLI used by this repository, the standard query flow exposed through `./query_graph.sh` still centers on `local`, `global`, `drift`, and `basic`, so treat `question_gen_system_prompt.txt` as an advanced or future-facing prompt rather than part of the default repo workflow.

---

## Customisation Guide

| Goal | Action |
|------|--------|
| Generate auto-tuned indexing prompts | Run `./auto_tune.sh`, then index with `GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh` |
| Add a new entity type | Add to `entity_types` in `settings.yaml` **and** add few-shot examples in `extract_graph.txt` |
| Change community report structure | Edit the JSON schema definition in `community_report_graph.txt` |
| Change claim categories | Edit the few-shot examples in `extract_claims.txt` |
| Adjust answer format | Edit the format instructions in `local_search_system_prompt.txt` |
| Different language | Translate all prompt instructions; set `language` in `settings.yaml` |
| Domain-specific entity types | Replace the generic entity type list with domain vocabulary (e.g. `drug, gene, disease, symptom` for biomedical) |
| Change scoring rubric for community reports | Edit the rating instructions in `community_report_graph.txt` |

After changing any indexing prompt file, **clear the matching LLM cache** before re-indexing. Use `cache/` for the baseline config and `cache_auto/` for `settings.auto.yaml`, or just run `./update_graph.sh` with the default `CLEAR_CACHE=true`. The cache is keyed on input hash, which includes prompt content.
