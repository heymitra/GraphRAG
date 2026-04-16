# GraphRAG Auto-Tuning Deep Dive

This document explains Microsoft GraphRAG auto-tuning in implementation terms, using the upstream GraphRAG 3.0.6 code that is installed in this workspace. It is intentionally not based on a single corpus result.

Use this together with:

- [Auto Prompt Tuning](auto_tuning.md) for the repo wrapper workflow
- [Indexing Pipeline](indexing_pipeline.md) for the standard GraphRAG indexing stages
- [Prompts Reference](prompts.md) for the prompt files used by this repo

## Scope and terminology

In GraphRAG 3.0.6, "auto tuning" means prompt generation from the corpus. It is not model fine-tuning.

The upstream implementation:

- reads a sample of corpus chunks
- asks the LLM to infer domain/task framing
- may infer entity types
- generates a few new indexing prompts
- writes those prompt files to disk

Then indexing runs using those generated prompts.

The key consequence is:

- auto-tuning can change extraction behavior a lot
- but it does not change the underlying indexing algorithm

## Upstream implementation entry points

Useful upstream files to inspect in this workspace:

- `graphrag/api/prompt_tune.py`
- `graphrag/cli/prompt_tune.py`
- `graphrag/prompt_tune/loader/input.py`
- `graphrag/prompt_tune/generator/entity_types.py`
- `graphrag/prompt_tune/generator/entity_relationship.py`
- `graphrag/prompt_tune/generator/extract_graph_prompt.py`
- `graphrag/prompt_tune/template/extract_graph.py`
- `graphrag/index/workflows/factory.py`
- `graphrag/index/operations/extract_graph/graph_extractor.py`
- `graphrag/index/operations/extract_graph/extract_graph.py`
- `graphrag/index/operations/finalize_entities.py`
- `graphrag/index/operations/finalize_relationships.py`

In this repo those live under:

- `graphrag-env/lib/python3.12/site-packages/graphrag/...`

## What prompt-tune generates in GraphRAG 3.0.6

The upstream prompt-tune flow writes three files:

- `extract_graph.txt`
- `summarize_descriptions.txt`
- `community_report_graph.txt`

It does not generate:

- claims prompts
- query prompts
- a canonicalization prompt
- a separate entity-resolution stage

In this repo, the generated files are stored in `prompts_auto/`.

## Upstream prompt-tune control flow

The main function is `generate_indexing_prompts(...)` in `graphrag/api/prompt_tune.py`.

The sequence is:

1. Chunk documents.
2. Select a subset of chunks.
3. Create the LLM instance from config.
4. Infer `domain` if not explicitly supplied.
5. Detect `language` if not explicitly supplied.
6. Generate a `persona`.
7. Generate a community report ranking description.
8. Optionally generate entity types if `discover_entity_types=True`.
9. Generate entity/relationship examples from sampled chunks.
10. Build the final extraction prompt from:
    - entity types or untyped mode
    - sampled chunks
    - generated examples
    - language
    - token budget
11. Build the entity summarization prompt.
12. Build the community summarization prompt.
13. Write the three generated prompt files.

This is important for interpretation:

- prompt-tune is optimizing prompt wording and examples
- it is not learning persistent model weights
- it is highly dependent on the sampled chunks

## How chunk sampling works

Chunk loading is implemented in `graphrag/prompt_tune/loader/input.py`.

The supported selection modes are:

- `all`
- `random`
- `top`
- `auto`

Behavior:

- `top`: first `limit` chunks
- `random`: random `limit` chunks
- `auto`: embed a sampled subset, compute a centroid, and keep chunks nearest the center
- `all`: falls through and returns the full chunk set

Why this matters:

- different selections can produce meaningfully different prompt files
- `random` introduces run-to-run variance
- `auto` may bias toward "central" or average-looking chunks
- small or skewed corpora can over-specialize the generated prompts

## Baseline vs auto-tuned execution paths

### Baseline path

Baseline indexing is:

1. load documents
2. chunk documents
3. run `extract_graph` with the configured baseline prompt files
4. continue through the standard indexing workflows

### Auto-tuned path

Auto-tuned indexing is:

1. run `prompt-tune`
2. generate prompt files from corpus samples
3. run the same standard indexing workflows
4. but use the generated prompt files for the tuned prompt slots

### What actually differs

What changes:

- prompt text
- prompt examples
- possibly the entity type schema
- output/cache/log directories in a tuned companion config like `settings.auto.yaml`

What does not change:

- the standard indexing workflow list
- the graph extractor parser
- the merge logic
- the finalization logic
- the lack of a dedicated alias-resolution stage

## Shared indexing pipeline

The upstream standard pipeline is defined in `graphrag/index/workflows/factory.py`.

The standard workflow list is:

1. `load_input_documents`
2. `create_base_text_units`
3. `create_final_documents`
4. `extract_graph`
5. `finalize_graph`
6. `extract_covariates`
7. `create_communities`
8. `create_final_text_units`
9. `create_community_reports`
10. `generate_text_embeddings`

So baseline and auto-tuned approaches are not two different graph-building algorithms. They are the same pipeline with different prompt inputs, plus an extra pre-index prompt generation phase on the auto-tuned path.

## Why there is no dedicated canonicalization stage

There is no dedicated alias/canonicalization/entity-resolution stage in either baseline or auto-tuned indexing.

### Implementation evidence

The extractor in `graphrag/index/operations/extract_graph/graph_extractor.py` turns each extracted entity into only:

- `title`
- `type`
- `description`
- `source_id`

There is no explicit field for:

- canonical name
- alias list
- mention span
- entity-linking confidence
- cross-document entity ID before exact-title merge

Then the merge logic in `graphrag/index/operations/extract_graph/extract_graph.py` groups entities by exact `["title", "type"]`.

Later, `graphrag/index/operations/finalize_entities.py` deduplicates by exact `title`, and `graphrag/index/operations/finalize_relationships.py` deduplicates by exact `(source, target)`.

This means the system assumes:

- if two extractions should be the same node, the prompt/model should emit the same normalized title string

### Practical implication

If the model emits:

- `BIN LADIN`
- `OSAMA BIN LADIN`
- `BIN LADEN`

the pipeline treats those as different nodes unless they become exact string matches upstream.

### Why Microsoft may have designed it this way

The code does not state the product reasoning explicitly, but the implementation strongly suggests these priorities:

- keep the indexing pipeline simpler
- avoid risky false merges
- let prompts control naming consistency
- perform safe exact-string deduplication rather than heuristic alias resolution

This is a defensible engineering choice, but it means prompt quality has to carry more of the burden for entity consolidation.

## How auto-tuning can help

Auto-tuning can improve extraction when the baseline prompts are too generic for the corpus.

Typical improvements to expect:

- more domain-specific entity types
- better examples inside `extract_graph.txt`
- community report language that matches the corpus domain
- better extraction language when the corpus is not English
- more semantically precise typing for key actors

In general, it is best thought of as a domain-adaptation step for prompts.

## How auto-tuning can hurt

Auto-tuning can also reduce quality, depending on the corpus and settings.

Common failure modes:

- inferred ontology becomes too narrow
- sample selection overfits to a subset of the corpus
- central chunks omit important edge cases
- entity naming becomes less stable
- graph recall drops even if type specificity improves
- prompt quality varies between runs when `selection_method=random`

So a smaller graph is not automatically "worse", and a larger graph is not automatically "better". The tradeoff is often between:

- specificity
- recall
- consistency
- graph compactness

## Important flag semantics

These are worth understanding before comparing runs.

### `--domain` / `DOMAIN`

- If provided, the prompt-tune pipeline uses your supplied domain framing.
- If omitted, GraphRAG infers a domain from sampled chunks.

Why test it:

- inferred domains can drift toward whatever the sampled chunks emphasize
- an explicit domain can stabilize prompt behavior

### `--language` / `LANGUAGE`

- If omitted, GraphRAG detects language from sampled chunks.
- If set, the prompts are generated around that language.

Why test it:

- useful for multilingual or noisy corpora
- can reduce variability in generated prompt wording

### `--selection-method`

Allowed upstream values:

- `all`
- `random`
- `top`
- `auto`

Why test it:

- this controls which chunks shape the generated prompts
- it is often one of the biggest sources of prompt variance

### `--limit`

- Used mainly with `random` and `top`
- Larger limits expose more corpus variety
- Smaller limits can make prompts faster and more brittle

### `--n-subset-max` and `--k`

These matter for `--selection-method=auto`.

- `n-subset-max`: how many chunks are embedded before sampling
- `k`: how many chunks are selected after centroid-based filtering

Why test them:

- they strongly affect what "representative" means in auto mode

### `--discover-entity-types`

This flag is especially important.

- `true`: GraphRAG first generates entity types from the sampled corpus
- `false`: GraphRAG does not reuse the baseline schema; instead it falls back to the untyped extraction template in `graphrag/prompt_tune/template/extract_graph.py`

That means `false` should be read as:

- "let the extraction prompt operate without a fixed discovered type list"

not as:

- "use the baseline entity types"

### `--max-tokens`

- Controls the token budget for building the extraction prompt
- Can limit how many examples fit into the final generated prompt

### `--min-examples-required`

- Sets the minimum number of examples that must be kept when assembling `extract_graph.txt`

Why test it:

- too few examples can make the prompt generic
- too many examples can overfit and consume context budget

### `--chunk-size` and `--overlap`

- Affect the chunks used for prompt generation
- Can change the shape of the examples and inferred ontology

Why test them:

- smaller chunks bias toward local details
- larger chunks preserve broader context

## Repo-wrapper notes for this project

This repo adds some wrapper behavior around upstream GraphRAG:

- `auto_tune.sh` stages the config into a GraphRAG 3.x runtime root
- the wrapper caps effective `LIMIT` to the available number of chunks
- `settings.auto.yaml` isolates tuned outputs into `output_auto/`, `cache_auto/`, and `logs_auto/`
- the frontend can run prompt-tune automatically on upload

Important repo-specific nuance:

- upload-time auto-tune flags such as `CHUNK_SIZE` and `OVERLAP` affect prompt generation
- but the subsequent indexing run still uses the active GraphRAG config staged for indexing

So in this repo, prompt-tune settings and index settings can diverge if you override the prompt-tune flags without also changing the config.

## What is good to test and compare

To understand GraphRAG auto-tuning fairly, compare runs systematically rather than reading too much into one pair of outputs.

### Good experiment axes

1. Baseline vs auto-tuned with all defaults held constant.
2. `DISCOVER_ENTITY_TYPES=true` vs `false`.
3. `SELECTION_METHOD=random` vs `auto` vs `top` vs `all`.
4. Explicit `DOMAIN` vs inferred domain.
5. Prompt-tune on a single document vs prompt-tune on a representative corpus.
6. Different `LIMIT` values.
7. Different `CHUNK_SIZE` and `OVERLAP` values.
8. Repeated runs with `random` selection to measure variance.

### Good things to measure

Do not measure only row counts.

Useful comparison metrics:

- number of entities, relationships, claims, communities
- retention of critical entity classes
- type specificity and type correctness
- alias fragmentation / duplicate person and organization nodes
- key node degree and graph centrality stability
- relationship plausibility and coverage
- community title usefulness and report quality
- query answer quality on the indexed outputs
- runtime and API cost

### A practical comparison matrix

Start with this:

1. `settings.yaml` baseline
2. `settings.auto.yaml` with:
   - `DISCOVER_ENTITY_TYPES=true`
   - `SELECTION_METHOD=random`
   - explicit `DOMAIN`
3. same as above but `DISCOVER_ENTITY_TYPES=false`
4. same as above but `SELECTION_METHOD=auto`
5. same as above but `SELECTION_METHOD=all` if the corpus is small enough

Then compare:

- raw counts
- duplicate identity rate
- key entity retention
- community usefulness
- query-answer usefulness

## Interpreting outcomes

A better auto-tuned run usually means:

- more useful domain types
- equal or better key entity retention
- fewer misleading generic types
- stable naming for major entities
- improved community reports

A worse auto-tuned run usually looks like:

- narrower ontology
- fewer but not better entities
- more fragmented identities
- loss of important locations/assets/events
- communities that are more generic or over-themed

The correct conclusion is usually not "auto-tune works" or "auto-tune fails". It is:

- auto-tune changed the prompt priors
- that shift either aligned with your task or did not

## Bottom line

Microsoft GraphRAG auto-tuning is best understood as:

- a corpus-adaptive prompt bootstrapping step
- not a separate extraction algorithm
- not a model fine-tuning mechanism
- not an entity-resolution system

It can help a lot when baseline prompts are too generic for a domain. It can also hurt when the sampled corpus drives the prompt toward a schema that is too narrow or unstable for your downstream use case.
