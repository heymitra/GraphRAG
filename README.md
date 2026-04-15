# GraphRAG Neo4j Integration

Extract knowledge graphs from documents with [Microsoft GraphRAG](https://github.com/microsoft/graphrag), inspect them in Neo4j, and compare baseline prompts against auto-tuned prompts without overwriting your main pipeline output.

## Supported Version

This repository is pinned to **GraphRAG 2.7.1**.

- The project config in `settings.yaml` uses the 2.x schema.
- Installing unpinned `graphrag` now pulls a 3.x release, which uses a different config shape and is not drop-in compatible with this repo.
- Use `requirements.txt` so new environments install the compatible version automatically.

## Features

- **PDF ingestion** with `extract_pdf.py`
- **GraphRAG indexing** for entities, relationships, claims, and communities
- **Neo4j import** for all GraphRAG output tables
- **Flask frontend** for uploads, pipeline logs, and graph exploration
- **Auto prompt tuning workflow** with isolated tuned prompts, cache, logs, and output
- **Manual prompt tuning support** for claims and query prompts

## Project Structure

```text
├── auto_tune.sh          # Generate auto-tuned indexing prompts into prompts_auto/
├── settings.yaml         # Baseline GraphRAG config
├── settings.auto.yaml    # Tuned GraphRAG config using prompts_auto/ and output_auto/
├── prompts/              # Baseline prompt files
├── input/                # Source text files
├── output/               # Baseline GraphRAG output
├── output_auto/          # Tuned GraphRAG output (generated, git-ignored)
├── import_neo4j.py       # Neo4j import script
├── update_graph.sh       # Re-index + Neo4j import using the active config
├── frontend/app.py       # Web UI; respects GRAPHRAG_CONFIG
└── docs/                 # Deeper technical docs
```

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv graphrag-env
source graphrag-env/bin/activate
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If you already have an older project environment, update the compatible GraphRAG patch release:

```bash
python -m pip install graphrag==2.7.1
```

### 3. Configure your OpenAI key

Create `.env` in the project root:

```dotenv
GRAPHRAG_API_KEY=your_openai_api_key
GRAPHRAG_API_BASE=https://api.openai.com/v1
```

### 4. Start Neo4j

```bash
docker run -d \
  --name graphrag-neo4j \
  -p 7475:7474 -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/graphrag123 \
  neo4j:latest
```

- Browser: `http://localhost:7475`
- Bolt: `bolt://localhost:7688`

## Baseline Usage

### Rebuild the baseline graph

```bash
./update_graph.sh
```

The script now reads the active GraphRAG config, clears the matching cache directory, runs indexing, and imports the matching output directory into Neo4j.

### Start the frontend

```bash
source graphrag-env/bin/activate
python frontend/app.py
```

Open `http://localhost:8501`.

### Run baseline queries

```bash
source graphrag-env/bin/activate
python -m graphrag query --root . --config settings.yaml -m local  -q "What are the main entities and relationships?"
python -m graphrag query --root . --config settings.yaml -m global -q "What are the main themes in this corpus?"
python -m graphrag query --root . --config settings.yaml -m drift  -q "How are the main actors connected?"
python -m graphrag query --root . --config settings.yaml -m basic  -q "Find documents about topic X"
```

## Auto Prompt Tuning

GraphRAG auto tuning in this repo is for **indexing prompts**. In the supported 2.7.1 workflow it generates:

- `prompts_auto/extract_graph.txt`
- `prompts_auto/summarize_descriptions.txt`
- `prompts_auto/community_report_graph.txt`

It does **not** generate:

- `extract_claims.txt`
- `community_report_text.txt`
- local/global/drift/basic query prompts

Those remain manual edits.

### 1. Generate tuned prompts

```bash
source graphrag-env/bin/activate
DOMAIN="your corpus domain" ./auto_tune.sh
```

Useful environment variables:

```bash
DOMAIN="biotech research" \
LANGUAGE="English" \
SELECTION_METHOD="random" \
LIMIT="15" \
DISCOVER_ENTITY_TYPES="false" \
./auto_tune.sh
```

`auto_tune.sh` writes prompts to `prompts_auto/` and keeps your baseline prompts untouched.

### 2. Run the tuned pipeline

```bash
source graphrag-env/bin/activate
GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh
```

`settings.auto.yaml` is already configured to:

- read the same `input/`
- use `prompts_auto/` for the supported auto-tuned indexing prompts
- write artifacts to `output_auto/`
- use separate cache and logs in `cache_auto/` and `logs_auto/`

### 3. Launch the frontend against tuned output

```bash
source graphrag-env/bin/activate
GRAPHRAG_CONFIG=settings.auto.yaml python frontend/app.py
```

The frontend now derives its output/cache directories from the active config, so the tuned UI reads `output_auto/` automatically.

### 4. Compare baseline vs tuned results

Compare the same question against both configs:

```bash
source graphrag-env/bin/activate

python -m graphrag query --root . --config settings.yaml      -m local  -q "What are the main entities and relationships?"
python -m graphrag query --root . --config settings.auto.yaml -m local  -q "What are the main entities and relationships?"

python -m graphrag query --root . --config settings.yaml      -m global -q "What themes dominate this corpus?"
python -m graphrag query --root . --config settings.auto.yaml -m global -q "What themes dominate this corpus?"
```

When comparing, look at:

- entity type quality
- relationship recall and phrasing
- community report titles and summaries
- answer grounding and citation quality
- whether the tuned graph produces better Neo4j structure for your domain

## Manual Prompt Tuning

Use manual tuning for anything auto tuning does not cover.

### Indexing prompts that require re-indexing

- `prompts/extract_graph.txt`
- `prompts/summarize_descriptions.txt`
- `prompts/extract_claims.txt`
- `prompts/community_report_graph.txt`
- `prompts/community_report_text.txt`

After changing indexing prompts, re-run the relevant pipeline:

```bash
./update_graph.sh
# or
GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh
```

### Query prompts that do not require re-indexing

- `prompts/local_search_system_prompt.txt`
- `prompts/global_search_map_system_prompt.txt`
- `prompts/global_search_reduce_system_prompt.txt`
- `prompts/global_search_knowledge_system_prompt.txt`
- `prompts/drift_search_system_prompt.txt`
- `prompts/drift_reduce_prompt.txt`
- `prompts/basic_search_system_prompt.txt`

After changing query prompts, just rerun `graphrag query`.

## Adding Documents

### Convert a PDF to text

```bash
source graphrag-env/bin/activate
python extract_pdf.py
```

### Add a `.txt` file directly

Drop one text file per source document into `input/`, then rerun the baseline or tuned pipeline.

## Graph Schema

### Nodes

| Label | Key properties |
|-------|---------------|
| `Document` | `id`, `title`, `text`, `creation_date`, `metadata` |
| `TextUnit` | `id`, `text`, `n_tokens` |
| `Entity` | `id`, `name`, `type`, `description`, `degree`, `x`, `y` |
| `Claim` | `id`, `covariate_type`, `type`, `description`, `status`, `subject_id`, `object_id` |
| `Community` | `id`, `community`, `level`, `title`, `size`, `period`, `parent`, `children`, `relationship_ids`, `text_unit_ids`, `is_root`, `is_final` |
| `CommunityReport` | `id`, `community`, `level`, `parent`, `children`, `title`, `summary`, `full_content`, `findings`, `rank`, `is_root`, `is_final` |

### Edges

| Relationship | From → To | Source |
|-------------|-----------|--------|
| `CONTAINS` | `Document` → `TextUnit` | `text_units.document_ids` |
| `MENTIONED_IN` | `Entity` → `TextUnit` | `text_units.entity_ids` |
| `RELATED` | `Entity` → `Entity` | `relationships` |
| `EXTRACTED_FROM` | `Claim` → `TextUnit` | `covariates.text_unit_id` |
| `ABOUT_SUBJECT` | `Claim` → `Entity` | `covariates.subject_id` |
| `ABOUT_OBJECT` | `Claim` → `Entity` | `covariates.object_id` |
| `BELONGS_TO` | `Entity` → `Community` | `communities.entity_ids` |
| `PARENT_OF` | `Community` → `Community` | `communities.parent` |
| `SUPPORTED_BY` | `Community` → `TextUnit` | `communities.text_unit_ids` |
| `DESCRIBES` | `CommunityReport` → `Community` | `community_reports.community` |

## Example Cypher Queries

```cypher
MATCH (n) RETURN labels(n) AS Type, count(n) AS Count ORDER BY Count DESC

MATCH (e:Entity)
RETURN e.name, e.type, e.degree
ORDER BY e.degree DESC
LIMIT 10

MATCH (e:Entity)-[r:RELATED]->(e2:Entity)
RETURN e.name, r.description, e2.name
LIMIT 25
```

## Docs

- [docs/README.md](docs/README.md)
- [docs/auto_tuning.md](docs/auto_tuning.md)
- [docs/prompts.md](docs/prompts.md)
- [docs/configuration.md](docs/configuration.md)
- [docs/search.md](docs/search.md)
- [docs/neo4j.md](docs/neo4j.md)

## Troubleshooting

| Problem | Fix |
|---------|-----|
| New environment installs GraphRAG 3.x | Recreate the venv and install from `requirements.txt` |
| Auto-tuned config fails with missing prompt files | Run `./auto_tune.sh` before using `settings.auto.yaml` |
| Stale baseline results | Re-run `./update_graph.sh` or delete `cache/` |
| Stale tuned results | Re-run `GRAPHRAG_CONFIG=settings.auto.yaml ./update_graph.sh` or delete `cache_auto/` |
| Frontend shows the wrong dataset | Launch it with the correct `GRAPHRAG_CONFIG` |
| Neo4j import reads the wrong output directory | Use `update_graph.sh` instead of calling `import_neo4j.py` manually, or set `OUTPUT_DIR` explicitly |

## License

For educational and research purposes.
