# GraphRAG Neo4j Integration

Extract knowledge graphs from documents using [Microsoft GraphRAG](https://github.com/microsoft/graphrag) and explore them interactively in Neo4j.

## Features

- **PDF ingestion** – convert PDFs to text with `extract_pdf.py`
- **Knowledge graph extraction** – entities, relationships, claims, and communities via GraphRAG
- **Full Neo4j import** – all GraphRAG node and edge types imported with correct properties
- **Interactive exploration** – Neo4j Browser + Jupyter notebook

## Project Structure

```
├── settings.yaml          # GraphRAG configuration (model, chunking, entity types)
├── prompts/               # Custom GraphRAG extraction prompts
├── input/                 # Input text files (git-ignored)
├── output/                # GraphRAG parquet outputs + LanceDB embeddings (git-ignored)
├── import_neo4j.py        # Neo4j import script
├── extract_pdf.py         # PDF → text extraction utility
├── update_graph.sh        # One-command rebuild: clear cache → index → import
└── inspect.ipynb          # Jupyter notebook for graph analysis
```

## Setup

### 1. Create Virtual Environment

> **macOS/Linux**: use `python3`, not `python`

```bash
python3 -m venv graphrag-env
source graphrag-env/bin/activate        # Windows: graphrag-env\Scripts\activate
pip install graphrag neo4j pandas jupyter matplotlib networkx PyPDF2 flask werkzeug
```

### 2. Configure API Key

Create a `.env` file in the project root:

```
GRAPHRAG_API_KEY=your_openai_api_key
GRAPHRAG_API_BASE=https://api.openai.com/v1   # optional, defaults to OpenAI
```

### 3. Start Neo4j

```bash
docker run -d \
  --name graphrag-neo4j \
  -p 7475:7474 -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/graphrag123 \
  neo4j:latest
```

> Browser: **http://localhost:7475** · Bolt: `bolt://localhost:7688`

## Usage

### Using the Web Explorer UI (Recommended)

You can use the built-in professional web frontend to upload PDFs, watch the live pipeline logs, and explore extracted knowledge (Entities, Claims, Relationships, and Communities) interactively.

```bash
# 1. Ensure Neo4j is running
docker start graphrag-neo4j

# 2. Start the web frontend
source graphrag-env/bin/activate
python3 frontend/app.py
```

Open **[http://localhost:8501](http://localhost:8501)** in your browser.

---

### Command Line Operations

#### Option A — One command script

```bash
./update_graph.sh
```

Clears cache → runs `python -m graphrag index` → imports to Neo4j.

### Option B — Manual steps

```bash
source graphrag-env/bin/activate

# 1. Convert a PDF (edit paths inside the script as needed)
python3 extract_pdf.py

# 2. Index with GraphRAG
rm -rf cache/
python3 -m graphrag index

# 3. Import to Neo4j
python3 import_neo4j.py
```

### Adding a new PDF

```bash
source graphrag-env/bin/activate
python3 - <<'EOF'
import PyPDF2, os

with open("input/your-document.pdf", "rb") as f:
    reader = PyPDF2.PdfReader(f)
    text = "\n\n".join(p.extract_text() for p in reader.pages)

with open("input/your-document.txt", "w") as out:
    out.write(text.strip())
print("Done")
EOF
./update_graph.sh
```

## Graph Schema

### Nodes

| Label | Key properties |
|-------|---------------|
| `Document` | `id`, `title`, `text`, `creation_date`, `metadata` |
| `TextUnit` | `id`, `text`, `n_tokens` |
| `Entity` | `id`, `name`, `type`, `description`, `degree`, `x`, `y` |
| `Claim` | `id`, `covariate_type`, `type`, `description`, `status`, `subject_id`, `object_id` |
| `Community` | `id`, `community`, `level`, `title`, `size`, `period`, `parent`, `children`, `is_root`, `is_final` |
| `CommunityReport` | `id`, `community`, `level`, `parent`, `children`, `title`, `summary`, `full_content`, `findings`, `rank`, `is_root`, `is_final` |

### Edges

| Relationship | From → To | Source |
|-------------|-----------|--------|
| `CONTAINS` | `Document` → `TextUnit` | `text_units.document_ids` |
| `MENTIONED_IN` | `Entity` → `TextUnit` | `text_units.entity_ids` |
| `RELATED` | `Entity` → `Entity` | `relationships` (+ `text_unit_ids` property) |
| `EXTRACTED_FROM` | `Claim` → `TextUnit` | `covariates.text_unit_id` |
| `ABOUT_SUBJECT` | `Claim` → `Entity` | `covariates.subject_id` |
| `ABOUT_OBJECT` | `Claim` → `Entity` | `covariates.object_id` |
| `BELONGS_TO` | `Entity` → `Community` | `communities.entity_ids` (one explicit membership per GraphRAG level; edge stores `level` and `is_final`) |
| `PARENT_OF` | `Community` → `Community` | `communities.parent` |
| `DESCRIBES` | `CommunityReport` → `Community` | `community_reports.community` (edge stores `level` and `is_final`) |

## Cypher Query Examples

```cypher
-- Node counts by type
MATCH (n) RETURN labels(n) AS Type, count(n) AS Count ORDER BY Count DESC

-- Most connected entities
MATCH (e:Entity) RETURN e.name, e.type, e.degree ORDER BY e.degree DESC LIMIT 10

-- Entity relationships
MATCH (e:Entity)-[r:RELATED]->(e2:Entity)
RETURN e.name, r.description, e2.name LIMIT 25

-- Claims with subjects
MATCH (c:Claim)-[:ABOUT_SUBJECT]->(e:Entity)
RETURN e.name, c.type, c.description LIMIT 10

-- Community membership + report summary
MATCH (e:Entity)-[:BELONGS_TO]->(comm:Community)<-[:DESCRIBES]-(cr:CommunityReport)
RETURN e.name, comm.title, cr.summary LIMIT 10

-- Community hierarchy tree
MATCH p=(root:Community)-[:PARENT_OF*]->(child:Community) RETURN p

-- Text evidence for a relationship
MATCH (e1:Entity)-[r:RELATED]->(e2:Entity)
RETURN e1.name, e2.name, r.description, r.text_unit_ids LIMIT 10
```

## Configuration (`settings.yaml`)

| Setting | Value |
|---------|-------|
| LLM model | `gpt-4o-mini` |
| Embedding model | `text-embedding-3-small` |
| Chunk size | 3000 tokens (300 overlap) |
| Entity types | organization, person, geo, event, product, technology |
| Max gleanings | 2 (graph) / 1 (claims) |
| Vector store | LanceDB at `output/lancedb` |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Stale extraction results | `rm -rf cache/` before re-indexing |
| Neo4j connection refused | Check container is running: `docker ps` |
| Wrong port | Browser → 7475, Bolt → 7688 (matches `import_neo4j.py`) |
| Claim→Entity edges missing | Entity names in claims must match GraphRAG output exactly |
| API rate limits | Reduce `max_gleanings` or `chunk_size` in `settings.yaml` |
| `No such file or directory` when running `graphrag` | Use `python3 -m graphrag ...` from the activated venv, or recreate the venv after moving the project folder |

## License

For educational and research purposes.
