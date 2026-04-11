# Configuration Reference

All pipeline behaviour is controlled from `settings.yaml`. This document annotates every significant setting with its purpose and trade-offs.

For the full list of available settings see the [official GraphRAG config docs](https://microsoft.github.io/graphrag/config/yaml/).

---

## Models

```yaml
models:
  default_chat_model:
    type: chat
    model_provider: openai
    auth_type: api_key
    api_key: ${GRAPHRAG_API_KEY}
    model: gpt-4o-mini
    model_supports_json: true
    concurrent_requests: 25
    async_mode: threaded
    retry_strategy: exponential_backoff
    max_retries: 10
    tokens_per_minute: null
    requests_per_minute: null

  default_embedding_model:
    type: embedding
    model_provider: openai
    api_key: ${GRAPHRAG_API_KEY}
    model: text-embedding-3-small
    concurrent_requests: 25
    async_mode: threaded
    retry_strategy: exponential_backoff
    max_retries: 10
```

| Setting | Effect |
|---------|--------|
| `model: gpt-4o-mini` | Cost-effective chat model for extraction, summarisation, and reporting. Replace with `gpt-4o` for higher extraction quality at higher cost. |
| `concurrent_requests: 25` | The key enabler of parallel chunk processing. The pipeline dispatches up to 25 simultaneous LLM calls. Lower this if you hit rate limits. |
| `retry_strategy: exponential_backoff` | Handles transient API errors gracefully; critical for long runs over large corpora. |
| `tokens_per_minute` / `requests_per_minute` | Set these to match your OpenAI tier's rate limits; leave `null` to use the API's own enforcement. |
| `model_supports_json: true` | Enables JSON output mode for structured responses (community reports, global search map phase). Set to `false` only if your model does not support it. |

**Azure OpenAI:** Uncomment `api_base` and `api_version` under each model to use an Azure-hosted deployment.

---

## Input

```yaml
input:
  storage:
    type: file
    base_dir: "input"
  file_type: text
```

One `.txt` file per source document placed in `input/`. The `file_type` field also supports `csv` and `json` for structured input formats.

---

## Chunking

```yaml
chunks:
  size: 3000
  overlap: 300
  group_by_columns: [id]
```

| Setting | Effect |
|---------|--------|
| `size: 3000` | Target chunk size in tokens. Chosen to balance LLM context window use against granularity. |
| `overlap: 300` | Tokens shared between adjacent chunks. Mitigates boundary effects where entities span chunk edges. |
| `group_by_columns: [id]` | Ensures chunks from the same document are grouped together before splitting. |

**Trade-offs:**

| Smaller chunks | Larger chunks |
|----------------|---------------|
| More granular extraction | Fewer LLM calls |
| More LLM calls and cost | More context per call |
| Better for dense, detail-rich documents | Better for narrative documents with broader context |

`overlap` does **not** mean multiple chunks are sent to the LLM as a combined window. Extraction is still one chunk at a time; overlap only ensures boundary-spanning entities appear fully in at least one chunk.

---

## Output, Cache, and Reporting

```yaml
output:
  type: file
  base_dir: "output"

cache:
  type: file
  base_dir: "cache"

reporting:
  type: file
  base_dir: "logs"
```

| Directory | Contents |
|-----------|---------|
| `output/` | Parquet tables, LanceDB vector store, GraphML snapshot |
| `cache/` | LLM response cache — keyed on input hash. Clearing this forces full re-extraction. |
| `logs/` | Run statistics and pipeline execution reports |

The `type` field for `output` and `cache` can be changed to `blob` (Azure Blob Storage) or `cosmosdb` for cloud deployments.

---

## Vector Store

```yaml
vector_store:
  default_vector_store:
    type: lancedb
    db_uri: output/lancedb
    container_name: default
```

LanceDB is the embedded vector store. No separate service is required — it stores data as files under `output/lancedb/`. The `container_name` groups all vector tables for this pipeline run.

---

## Graph Extraction

```yaml
extract_graph:
  model_id: default_chat_model
  prompt: "prompts/extract_graph.txt"
  entity_types: [organization, person, geo, event, product, technology]
  max_gleanings: 2
```

| Setting | Effect |
|---------|--------|
| `entity_types` | Controls what the LLM is asked to extract. Add domain-specific types here and update `extract_graph.txt` accordingly. |
| `max_gleanings: 2` | Allows up to 2 additional recall-improvement passes on the same chunk. `0` = single pass. Each gleaning pass adds one LLM call per chunk. |

With `max_gleanings: 2`, each chunk requires up to **3 LLM calls** for graph extraction (initial pass + 2 gleaning passes).

---

## NLP Extraction

```yaml
extract_graph_nlp:
  text_analyzer:
    extractor_type: regex_english
  async_mode: threaded
```

Non-LLM extraction path. Options for `extractor_type`: `regex_english`, `syntactic_parser`, `cfg`. In this repository, treat this as an auxiliary capability — the primary graph comes from the LLM extraction path.

---

## Description Summarisation

```yaml
summarize_descriptions:
  model_id: default_chat_model
  prompt: "prompts/summarize_descriptions.txt"
  max_length: 500
```

Controls the maximum word count of summarised descriptions. Increase `max_length` if entity descriptions are being truncated for complex, multi-faceted entities. The LLM is called for each entity or relationship that accumulated more than one description across chunks.

---

## Claim Extraction

```yaml
extract_claims:
  enabled: true
  model_id: default_chat_model
  prompt: "prompts/extract_claims.txt"
  description: "Any claims or facts that could be relevant to information discovery."
  max_gleanings: 1
```

| Setting | Effect |
|---------|--------|
| `enabled: true` | Set to `false` to skip claim extraction entirely — saves ~`N` LLM calls (significant cost reduction for large corpora). |
| `description` | Injected into the prompt as the claim scope definition. Customise to focus extraction on specific claim types. |
| `max_gleanings: 1` | Up to 2 LLM calls per chunk for claims. |

---

## Community Detection

```yaml
cluster_graph:
  max_cluster_size: 10
```

Controls the recursive splitting threshold for hierarchical Leiden community detection.

| Value | Effect |
|-------|--------|
| Lower (e.g. 5) | More, smaller communities — more focused summaries, more LLM calls in Step 7 |
| Higher (e.g. 20) | Fewer, larger communities — broader summaries, fewer LLM calls in Step 7 |

Communities are what enable global search and multi-scale graph reasoning. Choosing the right cluster size for your corpus size and domain is one of the most impactful tuning decisions.

---

## Community Reports

```yaml
community_reports:
  model_id: default_chat_model
  graph_prompt: "prompts/community_report_graph.txt"
  text_prompt: "prompts/community_report_text.txt"
  max_length: 2000
  max_input_length: 8000
```

| Setting | Effect |
|---------|--------|
| `max_length: 2000` | Maximum word count for each generated community report |
| `max_input_length: 8000` | Maximum tokens of entity/relationship context sent to the LLM per community. Large communities may be truncated to fit. |

---

## Embeddings and UMAP

```yaml
embed_text:
  model_id: default_embedding_model
  vector_store_id: default_vector_store

embed_graph:
  enabled: true

umap:
  enabled: true
```

| Setting | Effect |
|---------|--------|
| `embed_text` | Computes semantic text embeddings for entity descriptions, text units, and community reports |
| `embed_graph: enabled: true` | Computes structural graph embeddings (node2vec) capturing each entity's position in graph topology |
| `umap: enabled: true` | Reduces graph embeddings to 2D `x`/`y` coordinates for visualisation. Requires `embed_graph: true`. |

UMAP coordinates are only used for visualisation — they do not affect any retrieval or search behaviour.

---

## Snapshots

```yaml
snapshots:
  graphml: true
  embeddings: true
```

| Setting | Effect |
|---------|--------|
| `graphml: true` | Writes `output/graph.graphml` — standard graph export for Gephi, Cytoscape, yEd |
| `embeddings: true` | Persists embedding arrays as files alongside the main Parquet outputs |

Both are inspection and export artifacts; disabling them has no effect on search quality.

---

## Query Configuration

```yaml
local_search:
  chat_model_id: default_chat_model
  embedding_model_id: default_embedding_model
  prompt: "prompts/local_search_system_prompt.txt"

global_search:
  chat_model_id: default_chat_model
  map_prompt: "prompts/global_search_map_system_prompt.txt"
  reduce_prompt: "prompts/global_search_reduce_system_prompt.txt"
  knowledge_prompt: "prompts/global_search_knowledge_system_prompt.txt"

drift_search:
  chat_model_id: default_chat_model
  embedding_model_id: default_embedding_model
  prompt: "prompts/drift_search_system_prompt.txt"
  reduce_prompt: "prompts/drift_search_reduce_prompt.txt"

basic_search:
  chat_model_id: default_chat_model
  embedding_model_id: default_embedding_model
  prompt: "prompts/basic_search_system_prompt.txt"
```

All search methods read the same `output/` artifacts but operate on different subsets of them. See [Search Strategies](search.md) for behavioural details.

---

## Environment Variables

```bash
GRAPHRAG_API_KEY=sk-...          # OpenAI API key
GRAPHRAG_API_BASE=https://...    # Optional: Azure OpenAI endpoint
```

Set in `.env` (copy from `.env.template`). The API key is referenced in `settings.yaml` as `${GRAPHRAG_API_KEY}`.

---

## Cost Optimisation

| Change | Effect |
|--------|--------|
| `model: gpt-4o-mini` | Significantly cheaper than `gpt-4o`; adequate for most extraction tasks |
| `max_gleanings: 0` | Eliminates recall-improvement passes — reduces graph extraction calls by up to 3× |
| `extract_claims: enabled: false` | Skips claim extraction entirely — removes ~_N_ LLM calls |
| Increase `chunks.size` | Fewer chunks → fewer extraction calls; may reduce granularity |
| Increase `cluster_graph.max_cluster_size` | Fewer communities → fewer community report calls |
| Set `tokens_per_minute` / `requests_per_minute` | Avoids rate-limit errors on lower API tiers |
| Do not clear `cache/` between runs | Reuses all prior LLM responses for unchanged inputs |
