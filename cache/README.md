# cache/

LLM and embedding response cache for **baseline** GraphRAG runs.

GraphRAG stores hashed LLM responses here so repeated indexing runs with the same
input can reuse prior API calls, significantly reducing cost and latency.

**Safe to delete** — the pipeline will rebuild it automatically, but you will incur
fresh LLM API calls for every chunk.

> **Generated — do not commit.**
