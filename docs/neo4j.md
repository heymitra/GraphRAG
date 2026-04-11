# Neo4j Graph Schema

The `import_neo4j.py` script loads all GraphRAG Parquet outputs into a Neo4j property graph. This enables Cypher queries, graph algorithm execution, and visual exploration through the Neo4j Browser.

---

## Connection

```
Bolt URI:  bolt://localhost:7688
HTTP UI:   http://localhost:7475
Username:  neo4j
Password:  graphrag123
```

### Docker startup

```bash
docker run -d \
  --name graphrag-neo4j \
  -p 7475:7474 \
  -p 7688:7687 \
  -e NEO4J_AUTH=neo4j/graphrag123 \
  neo4j:latest
```

### Running the importer

```bash
source graphrag-env/bin/activate
python3 import_neo4j.py
```

The importer clears all existing data before loading. Run it after every `graphrag index` to keep Neo4j in sync with the Parquet outputs.

---

## Node Labels

### `Document`

```
id               string (UUID)
title            string
text             string
human_readable_id int
creation_date    string
metadata         string
```

One node per source `.txt` file.

---

### `TextUnit`

```
id               string (UUID)
text             string
n_tokens         int
human_readable_id int
```

One node per text chunk produced by the chunking step.

---

### `Entity`

```
id               string (UUID)
name             string          ← Entity.title from parquet
type             string          (organization / person / geo / event / product / technology)
description      string
human_readable_id int
frequency        int             (number of chunks mentioning this entity)
degree           int             (number of relationships)
x                float           (UMAP coordinate — visualisation only)
y                float           (UMAP coordinate — visualisation only)
```

One node per canonical entity. Note: the parquet field `title` is mapped to `name` in Neo4j.

---

### `Claim`

```
id               string (UUID)
covariate_type   string
type             string
description      string
status           string          (TRUE / FALSE / SUSPECTED)
source_text      string
subject_id       string          (entity name — used for ABOUT_SUBJECT edge)
object_id        string          (entity name — used for ABOUT_OBJECT edge)
start_date       string
end_date         string
human_readable_id int
```

---

### `Community`

```
id               string (UUID)
community        int             (community number — used for hierarchy joins)
level            int             (0 = finest, higher = broader)
title            string
size             int
period           string
parent           int             (-1 = root community)
human_readable_id int
```

---

### `CommunityReport`

```
id               string (UUID)
title            string
summary          string
full_content     string
full_content_json string         (JSON-serialised findings)
level            int
rank             float           (0–10 importance score)
rating_explanation string
findings         string          (JSON-serialised list)
period           string
size             int
human_readable_id int
```

---

## Relationship Types

```
(Document)        -[:CONTAINS]->       (TextUnit)
(Entity)          -[:MENTIONED_IN]->   (TextUnit)
(Entity)          -[:RELATED]->        (Entity)          + weight, description, text_unit_ids
(Claim)           -[:EXTRACTED_FROM]-> (TextUnit)
(Claim)           -[:ABOUT_SUBJECT]->  (Entity)
(Claim)           -[:ABOUT_OBJECT]->   (Entity)
(Entity)          -[:BELONGS_TO]->     (Community)
(Community)       -[:PARENT_OF]->      (Community)
(CommunityReport) -[:DESCRIBES]->      (Community)
```

### `RELATED` edge properties

| Property | Type | Description |
|----------|------|-------------|
| `id` | string | UUID from `relationships.parquet` |
| `weight` | float | Relationship strength (1–10) |
| `description` | string | Canonical relationship description |
| `human_readable_id` | int | Sequential display ID |
| `combined_degree` | int | Sum of source and target entity degrees |
| `text_unit_ids` | list[string] | IDs of TextUnits that evidence this relationship |

---

## Graph Diagram

```
Document
   │
   [:CONTAINS]
   ▼
TextUnit ◄─────────────────────────── Entity ──────► Community ──► Community (parent)
   ▲            [:MENTIONED_IN]          │                │
   │                                     │ [:RELATED]     │ [:PARENT_OF]
   │                                     ▼                ▼
   └─── Claim [:EXTRACTED_FROM]       Entity         Community
              │
              ├─ [:ABOUT_SUBJECT] ──► Entity
              └─ [:ABOUT_OBJECT]  ──► Entity

                                   Community ◄─── CommunityReport [:DESCRIBES]
```

---

## Indexes

```cypher
CREATE INDEX entity_id           IF NOT EXISTS FOR (n:Entity)          ON (n.id)
CREATE INDEX entity_name         IF NOT EXISTS FOR (n:Entity)          ON (n.name)
CREATE INDEX document_id         IF NOT EXISTS FOR (n:Document)        ON (n.id)
CREATE INDEX text_unit_id        IF NOT EXISTS FOR (n:TextUnit)        ON (n.id)
CREATE INDEX claim_id            IF NOT EXISTS FOR (n:Claim)           ON (n.id)
CREATE INDEX community_id        IF NOT EXISTS FOR (n:Community)       ON (n.id)
CREATE INDEX community_num       IF NOT EXISTS FOR (n:Community)       ON (n.community)
CREATE INDEX community_report_id IF NOT EXISTS FOR (n:CommunityReport) ON (n.id)
```

These indexes are created automatically by `import_neo4j.py` before each import run.

---

## Cypher Query Cookbook

### Graph statistics

```cypher
// Node counts by type
MATCH (n)
RETURN labels(n) AS NodeType, count(n) AS Count
ORDER BY Count DESC

// Relationship counts by type
MATCH ()-[r]->()
RETURN type(r) AS RelType, count(r) AS Count
ORDER BY Count DESC
```

---

### Entity exploration

```cypher
// Most connected entities (by relationship degree)
MATCH (e:Entity)
RETURN e.name, e.type, e.degree
ORDER BY e.degree DESC
LIMIT 10

// All organisations sorted by degree
MATCH (e:Entity {type: 'organization'})
RETURN e.name, e.description, e.degree
ORDER BY e.degree DESC
LIMIT 20

// Immediate neighbourhood of a specific entity
MATCH (e:Entity {name: 'ACME CORP'})-[r:RELATED]-(neighbour)
RETURN e.name, type(r), neighbour.name, r.description

// Shortest path between two entities
MATCH p = shortestPath(
  (a:Entity {name: 'ENTITY_A'})-[:RELATED*]-(b:Entity {name: 'ENTITY_B'})
)
RETURN p

// All relationships between two entities (multi-hop)
MATCH p = (a:Entity {name: 'ENTITY_A'})-[:RELATED*1..3]-(b:Entity {name: 'ENTITY_B'})
RETURN p
LIMIT 10
```

---

### Claims

```cypher
// All claims with their subjects
MATCH (c:Claim)-[:ABOUT_SUBJECT]->(e:Entity)
RETURN e.name, c.type, c.status, c.description
LIMIT 20

// Only confirmed (TRUE) claims
MATCH (c:Claim {status: 'TRUE'})-[:ABOUT_SUBJECT]->(e:Entity)
RETURN e.name, c.type, c.description

// Suspected claims for a specific entity
MATCH (c:Claim {status: 'SUSPECTED'})-[:ABOUT_SUBJECT]->(e:Entity {name: 'ACME CORP'})
RETURN c.type, c.description, c.source_text

// Claims linking two entities
MATCH (c:Claim)-[:ABOUT_SUBJECT]->(subj:Entity)
MATCH (c)-[:ABOUT_OBJECT]->(obj:Entity)
RETURN subj.name, c.type, obj.name, c.description
LIMIT 10

// Source text for a claim
MATCH (c:Claim)-[:EXTRACTED_FROM]->(t:TextUnit)
WHERE c.status = 'TRUE'
RETURN c.description, t.text
LIMIT 10
```

---

### Communities

```cypher
// Community hierarchy (full tree)
MATCH p = (root:Community)-[:PARENT_OF*]->(child:Community)
RETURN p

// Communities at a specific level
MATCH (c:Community {level: 0})
RETURN c.community, c.title, c.size
ORDER BY c.size DESC

// Top-ranked community reports
MATCH (cr:CommunityReport)
RETURN cr.title, cr.rank, cr.summary
ORDER BY cr.rank DESC
LIMIT 10

// Entities in a community with its report
MATCH (e:Entity)-[:BELONGS_TO]->(c:Community)<-[:DESCRIBES]-(cr:CommunityReport)
RETURN c.title, cr.rank, collect(e.name) AS members
ORDER BY cr.rank DESC
LIMIT 10

// Which community does a given entity belong to?
MATCH (e:Entity {name: 'ACME CORP'})-[:BELONGS_TO]->(c:Community)<-[:DESCRIBES]-(cr:CommunityReport)
RETURN c.level, c.title, cr.summary
ORDER BY c.level ASC
```

---

### Text evidence and provenance

```cypher
// Original text chunks mentioning an entity
MATCH (e:Entity {name: 'ACME CORP'})-[:MENTIONED_IN]->(t:TextUnit)
RETURN e.name, t.text
LIMIT 5

// Source text for a specific relationship
MATCH (e1:Entity)-[r:RELATED]->(e2:Entity)
WHERE r.description CONTAINS 'partnership'
UNWIND r.text_unit_ids AS tuid
MATCH (t:TextUnit {id: tuid})
RETURN e1.name, e2.name, r.description, t.text
LIMIT 5

// Full provenance chain: community report → source document
MATCH (cr:CommunityReport)-[:DESCRIBES]->(c:Community)
MATCH (e:Entity)-[:BELONGS_TO]->(c)
MATCH (e)-[:MENTIONED_IN]->(t:TextUnit)<-[:CONTAINS]-(d:Document)
WHERE cr.rank > 7
RETURN cr.title, cr.rank, d.title, count(t) AS supporting_chunks
ORDER BY cr.rank DESC
```
