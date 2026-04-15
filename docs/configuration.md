# Configuration Reference

All pipeline behavior is controlled from `settings.yaml`. The tuned companion config `settings.auto.yaml` uses the same GraphRAG 3.x schema with different prompt, output, cache, and reporting paths.

For the full list of available settings, see the [official GraphRAG config docs](https://microsoft.github.io/graphrag/config/yaml/).

This repository targets `graphrag==3.0.6`.

## Completion Models

```yaml
completion_models:
  default_completion_model:
    model_provider: openai
    model: gpt-4o-mini
    auth_method: api_key
    api_key: ${GRAPHRAG_API_KEY}
    retry:
      type: exponential_backoff
      max_retries: 10
```

| Setting | Effect |
|---------|--------|
| `model: gpt-4o-mini` | Cost-effective completion model for extraction, summarization, and reporting |
| `auth_method: api_key` | Reads `GRAPHRAG_API_KEY` from `.env` |
| `retry.max_retries: 10` | Retries transient API failures during long runs |

## Embedding Models

```yaml
embedding_models:
  default_embedding_model:
    model_provider: openai
    model: text-embedding-3-small
    auth_method: api_key
    api_key: ${GRAPHRAG_API_KEY}
    retry:
      type: exponential_backoff
      max_retries: 10
```

`text-embedding-3-small` keeps vector costs down while still working well for local, global, DRIFT, and basic search in this repo.

## Global Concurrency

```yaml
concurrent_requests: 25
async_mode: threaded
```

These are now top-level GraphRAG 3.x settings. They control default LLM parallelism across indexing and query operations.

## Input

```yaml
input:
  type: text

input_storage:
  type: file
  base_dir: "input"
```

One `.txt` file per source document lives in `input/`.

## Chunking

```yaml
chunking:
  type: tokens
  size: 3000
  overlap: 300
  encoding_model: o200k_base
```

| Setting | Effect |
|---------|--------|
| `size: 3000` | Larger chunks improve context coverage at the cost of chunk-level granularity |
| `overlap: 300` | Reduces boundary misses where entities span chunk edges |
| `encoding_model: o200k_base` | Tokenizer used for chunk sizing |

## Output, Cache, and Reporting

```yaml
output_storage:
  type: file
  base_dir: "output"

reporting:
  type: file
  base_dir: "logs"

cache:
  type: json
  storage:
    type: file
    base_dir: "cache"
```

| Directory | Contents |
|-----------|----------|
| `output/` | Parquet tables, LanceDB vector store, GraphML snapshot |
| `cache/` | LLM response cache |
| `logs/` | Run statistics and GraphRAG reports |

`settings.auto.yaml` switches those to `output_auto/`, `cache_auto/`, and `logs_auto/`.

## Vector Store

```yaml
vector_store:
  type: lancedb
  db_uri: output/lancedb
```

LanceDB is the embedded vector store used by the query layer. No separate service is required.

## Text Embeddings

```yaml
embed_text:
  embedding_model_id: default_embedding_model
```

GraphRAG 3.x uses a single `vector_store` block, so `embed_text` only needs the embedding model reference.

## Graph Extraction

```yaml
extract_graph:
  completion_model_id: default_completion_model
  prompt: "prompts/extract_graph.txt"
  entity_types: [organization, person, geo, event, product, technology]
  max_gleanings: 2
```

| Setting | Effect |
|---------|--------|
| `completion_model_id` | Which completion model performs extraction |
| `entity_types` | Types the prompt is asked to extract |
| `max_gleanings: 2` | Up to two recall-improvement passes per chunk |

## Description Summarization

```yaml
summarize_descriptions:
  completion_model_id: default_completion_model
  prompt: "prompts/summarize_descriptions.txt"
  max_length: 500
```

This merges repeated entity and relationship descriptions into a single canonical summary.

## NLP Graph Extraction

```yaml
extract_graph_nlp:
  text_analyzer:
    extractor_type: regex_english
```

This is the auxiliary non-LLM extraction path. The repo still uses the LLM path as the primary graph source.

## Claim Extraction

```yaml
extract_claims:
  enabled: true
  completion_model_id: default_completion_model
  prompt: "prompts/extract_claims.txt"
  description: "Any claims or facts that could be relevant to information discovery."
  max_gleanings: 1
```

Set `enabled: false` if you want a cheaper run without claim extraction.

## Community Detection and Reports

```yaml
cluster_graph:
  max_cluster_size: 10

community_reports:
  completion_model_id: default_completion_model
  graph_prompt: "prompts/community_report_graph.txt"
  text_prompt: "prompts/community_report_text.txt"
  max_length: 2000
  max_input_length: 8000
```

| Setting | Effect |
|---------|--------|
| `max_cluster_size: 10` | Controls how aggressively Leiden communities split |
| `max_length: 2000` | Maximum generated report length |
| `max_input_length: 8000` | Limits report context size |

## Snapshots

```yaml
snapshots:
  graphml: true
  embeddings: true
```

| Setting | Effect |
|---------|--------|
| `graphml: true` | Writes `graph.graphml` for external graph tools |
| `embeddings: true` | Persists embedding snapshot tables |

## Query Configuration

```yaml
local_search:
  completion_model_id: default_completion_model
  embedding_model_id: default_embedding_model
  prompt: "prompts/local_search_system_prompt.txt"

global_search:
  completion_model_id: default_completion_model
  map_prompt: "prompts/global_search_map_system_prompt.txt"
  reduce_prompt: "prompts/global_search_reduce_system_prompt.txt"
  knowledge_prompt: "prompts/global_search_knowledge_system_prompt.txt"

drift_search:
  completion_model_id: default_completion_model
  embedding_model_id: default_embedding_model
  prompt: "prompts/drift_search_system_prompt.txt"
  reduce_prompt: "prompts/drift_reduce_prompt.txt"

basic_search:
  completion_model_id: default_completion_model
  embedding_model_id: default_embedding_model
  prompt: "prompts/basic_search_system_prompt.txt"
```

GraphRAG 3.x renamed `chat_model_id` to `completion_model_id`.

## Tuned Config Differences

`settings.auto.yaml` changes only the parts needed for A/B testing:

- `output_storage.base_dir: "output_auto"`
- `cache.storage.base_dir: "cache_auto"`
- `reporting.base_dir: "logs_auto"`
- `vector_store.db_uri: output_auto/lancedb`
- `extract_graph.prompt: "prompts_auto/extract_graph.txt"`
- `summarize_descriptions.prompt: "prompts_auto/summarize_descriptions.txt"`
- `community_reports.graph_prompt: "prompts_auto/community_report_graph.txt"`

Everything else stays aligned with the baseline config.

## Repo Runtime Wrapper

GraphRAG 3.x expects the selected config to be named `settings.yaml` under the `--root` directory. This repo works around that by staging the chosen config into `.graphrag-runtime/` with absolute prompt and storage paths.

That logic lives in `graphrag_runtime.py`, and the normal entry points are:

- `./update_graph.sh`
- `./auto_tune.sh`
- `./query_graph.sh`
- `python frontend/app.py`
