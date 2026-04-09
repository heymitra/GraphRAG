import json
import pandas as pd
from neo4j import GraphDatabase
import sys

# --- CONFIGURATION ---
NEO4J_URI = "bolt://localhost:7688"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphrag123"
OUTPUT_DIR = "output"

# --- HELPERS ---

def _to_list(val):
    """Normalise numpy arrays / None / strings-that-look-like-lists to plain Python lists."""
    if val is None:
        return []
    if hasattr(val, 'tolist'):
        return [v for v in val.tolist() if v is not None]
    if isinstance(val, list):
        return [v for v in val if v is not None]
    if isinstance(val, str) and val.startswith('['):
        try:
            return [v for v in json.loads(val) if v is not None]
        except Exception:
            return []
    return []

def _clean(val, default=None):
    """Return None (or default) for NaN/empty, otherwise the value."""
    if val is None:
        return default
    try:
        import math
        if isinstance(val, float) and math.isnan(val):
            return default
    except Exception:
        pass
    return val

def _records(df):
    """Convert a DataFrame to a list of plain-Python dicts (no numpy scalars)."""
    rows = []
    for rec in df.to_dict('records'):
        clean = {}
        for k, v in rec.items():
            if hasattr(v, 'item') and getattr(v, 'ndim', 1) == 0:  # numpy 0-d scalar
                v = v.item()
            clean[k] = v
        rows.append(clean)
    return rows

# --- CONNECT TO NEO4J ---
def create_driver():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as session:
            session.run("RETURN 1")
        print("✅ Successfully connected to Neo4j")
        return driver
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        print("Please make sure Neo4j is running and credentials are correct.")
        sys.exit(1)

# --- INDEXES ---
def create_indexes(session):
    indexes = [
        "CREATE INDEX entity_id IF NOT EXISTS FOR (n:Entity) ON (n.id)",
        "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
        "CREATE INDEX document_id IF NOT EXISTS FOR (n:Document) ON (n.id)",
        "CREATE INDEX text_unit_id IF NOT EXISTS FOR (n:TextUnit) ON (n.id)",
        "CREATE INDEX claim_id IF NOT EXISTS FOR (n:Claim) ON (n.id)",
        "CREATE INDEX community_id IF NOT EXISTS FOR (n:Community) ON (n.id)",
        "CREATE INDEX community_num IF NOT EXISTS FOR (n:Community) ON (n.community)",
        "CREATE INDEX community_report_id IF NOT EXISTS FOR (n:CommunityReport) ON (n.id)",
    ]
    for idx in indexes:
        session.run(idx)

# --- NODE CREATORS ---

def clear_database(tx):
    tx.run("MATCH (n) DETACH DELETE n")

def create_documents(tx, batch):
    query = """
    UNWIND $batch AS row
    MERGE (d:Document {id: row.id})
    SET d.title       = row.title,
        d.text        = row.text,
        d.human_readable_id = row.human_readable_id,
        d.creation_date = row.creation_date,
        d.metadata    = row.metadata
    """
    tx.run(query, batch=batch)

def create_text_units(tx, batch):
    query = """
    UNWIND $batch AS row
    MERGE (t:TextUnit {id: row.id})
    SET t.text        = row.text,
        t.n_tokens    = row.n_tokens,
        t.human_readable_id = row.human_readable_id
    """
    tx.run(query, batch=batch)

def create_entity_nodes(tx, batch):
    query = """
    UNWIND $batch AS row
    MERGE (e:Entity {id: row.id})
    SET e.name        = row.title,
        e.type        = row.type,
        e.description = row.description,
        e.human_readable_id = row.human_readable_id,
        e.frequency   = row.frequency,
        e.degree      = row.degree,
        e.x           = row.x,
        e.y           = row.y
    """
    tx.run(query, batch=batch)

def create_relationships(tx, batch):
    """Entity-to-Entity RELATED edges, carrying text_unit_ids as a list property."""
    query = """
    UNWIND $batch AS row
    MATCH (src:Entity {name: row.source})
    MATCH (tgt:Entity {name: row.target})
    MERGE (src)-[r:RELATED {id: row.id}]->(tgt)
    SET r.weight           = row.weight,
        r.description      = row.description,
        r.human_readable_id = row.human_readable_id,
        r.combined_degree  = row.combined_degree,
        r.text_unit_ids    = row.text_unit_ids
    """
    tx.run(query, batch=batch)

def create_claims(tx, batch):
    query = """
    UNWIND $batch AS row
    MERGE (c:Claim {id: row.id})
    SET c.covariate_type  = row.covariate_type,
        c.type            = row.type,
        c.description     = row.description,
        c.status          = row.status,
        c.source_text     = row.source_text,
        c.human_readable_id = row.human_readable_id,
        c.start_date      = row.start_date,
        c.end_date        = row.end_date,
        c.subject_id      = row.subject_id,
        c.object_id       = row.object_id
    """
    tx.run(query, batch=batch)

def create_communities(tx, batch):
    query = """
    UNWIND $batch AS row
    MERGE (c:Community {id: row.id})
    SET c.title       = row.title,
        c.community   = row.community,
        c.level       = row.level,
        c.size        = row.size,
        c.period      = row.period,
        c.parent      = row.parent,
        c.human_readable_id = row.human_readable_id
    """
    tx.run(query, batch=batch)

def create_community_reports(tx, batch):
    query = """
    UNWIND $batch AS row
    MERGE (cr:CommunityReport {id: row.id})
    SET cr.title               = row.title,
        cr.summary             = row.summary,
        cr.full_content        = row.full_content,
        cr.full_content_json   = row.full_content_json,
        cr.level               = row.level,
        cr.rank                = row.rank,
        cr.rating_explanation  = row.rating_explanation,
        cr.findings            = row.findings,
        cr.period              = row.period,
        cr.size                = row.size,
        cr.human_readable_id   = row.human_readable_id
    """
    tx.run(query, batch=batch)

# --- EDGE CREATORS ---

def create_document_text_unit_edges(tx, text_units_batch):
    """Document -[:CONTAINS]-> TextUnit"""
    query = """
    UNWIND $batch AS row
    MATCH (t:TextUnit {id: row.id})
    UNWIND row.document_ids AS doc_id
    MATCH (d:Document {id: doc_id})
    MERGE (d)-[:CONTAINS]->(t)
    """
    rows = [u for u in text_units_batch if u.get('document_ids')]
    if rows:
        tx.run(query, batch=rows)

def create_entity_text_unit_edges(tx, text_units_batch):
    """Entity -[:MENTIONED_IN]-> TextUnit"""
    query = """
    UNWIND $batch AS row
    MATCH (t:TextUnit {id: row.id})
    UNWIND row.entity_ids AS entity_id
    MATCH (e:Entity {id: entity_id})
    MERGE (e)-[:MENTIONED_IN]->(t)
    """
    rows = [u for u in text_units_batch if u.get('entity_ids')]
    if rows:
        tx.run(query, batch=rows)

def create_claim_edges(tx, claims_batch):
    """Claim -[:EXTRACTED_FROM]-> TextUnit
       Claim -[:ABOUT_SUBJECT]-> Entity (matched by name)
       Claim -[:ABOUT_OBJECT]->  Entity (matched by name)
    """
    tx.run("""
    UNWIND $batch AS row
    MATCH (c:Claim {id: row.id})
    MATCH (t:TextUnit {id: row.text_unit_id})
    MERGE (c)-[:EXTRACTED_FROM]->(t)
    """, batch=[c for c in claims_batch if c.get('text_unit_id')])

    tx.run("""
    UNWIND $batch AS row
    MATCH (c:Claim {id: row.id})
    MATCH (e:Entity {name: row.subject_id})
    MERGE (c)-[:ABOUT_SUBJECT]->(e)
    """, batch=[c for c in claims_batch
                if c.get('subject_id') and c['subject_id'] not in ('', 'NONE')])

    tx.run("""
    UNWIND $batch AS row
    MATCH (c:Claim {id: row.id})
    MATCH (e:Entity {name: row.object_id})
    MERGE (c)-[:ABOUT_OBJECT]->(e)
    """, batch=[c for c in claims_batch
                if c.get('object_id') and c['object_id'] not in ('', 'NONE', 'None')])

def create_entity_community_edges(tx, communities_batch):
    """Entity -[:BELONGS_TO]-> Community"""
    query = """
    UNWIND $batch AS row
    MATCH (comm:Community {id: row.id})
    UNWIND row.entity_ids AS entity_id
    MATCH (e:Entity {id: entity_id})
    MERGE (e)-[:BELONGS_TO]->(comm)
    """
    rows = [c for c in communities_batch if c.get('entity_ids')]
    if rows:
        tx.run(query, batch=rows)

def create_community_hierarchy_edges(tx, communities_batch):
    """Community -[:PARENT_OF]-> Community (multi-level hierarchy)"""
    query = """
    UNWIND $batch AS row
    MATCH (parent:Community {community: row.parent})
    MATCH (child:Community  {community: row.community})
    MERGE (parent)-[:PARENT_OF]->(child)
    """
    # Only communities that have a real parent (parent != -1 and != None)
    rows = [c for c in communities_batch
            if c.get('parent') is not None and c['parent'] != -1 and c['parent'] != '']
    if rows:
        tx.run(query, batch=rows)

def create_community_report_edges(tx, reports_batch):
    """CommunityReport -[:DESCRIBES]-> Community"""
    query = """
    UNWIND $batch AS row
    MATCH (cr:CommunityReport {id: row.id})
    MATCH (c:Community {community: row.community})
    MERGE (cr)-[:DESCRIBES]->(c)
    """
    tx.run(query, batch=reports_batch)

def link_entities_to_communities(tx, communities_batch):
    """Alias kept for backward compat – delegates to create_entity_community_edges."""
    create_entity_community_edges(tx, communities_batch)

def link_community_reports(tx, community_reports_batch):
    """Alias kept for backward compat – delegates to create_community_report_edges."""
    create_community_report_edges(tx, community_reports_batch)

def _prep_text_units(df):
    """Convert text_units DataFrame to records with proper list fields."""
    rows = _records(df)
    for r in rows:
        r['document_ids']    = _to_list(r.get('document_ids'))
        r['entity_ids']      = _to_list(r.get('entity_ids'))
        r['relationship_ids'] = _to_list(r.get('relationship_ids'))
        r['covariate_ids']   = _to_list(r.get('covariate_ids'))
    return rows

def _prep_communities(df):
    """Convert communities DataFrame to records with proper list fields."""
    rows = _records(df)
    for r in rows:
        r['entity_ids']       = _to_list(r.get('entity_ids'))
        r['relationship_ids'] = _to_list(r.get('relationship_ids'))
        r['text_unit_ids']    = _to_list(r.get('text_unit_ids'))
        r['children']         = _to_list(r.get('children'))
        # Keep parent as int; -1 means root
        if r.get('parent') is None:
            r['parent'] = -1
        elif hasattr(r['parent'], 'item'):
            r['parent'] = r['parent'].item()
    return rows

def _prep_relationships(df):
    """Convert relationships DataFrame; normalise text_unit_ids to list."""
    rows = _records(df)
    for r in rows:
        r['text_unit_ids'] = _to_list(r.get('text_unit_ids'))
    return rows

def _prep_community_reports(df):
    """Serialise complex fields (findings, full_content_json) to JSON strings."""
    rows = _records(df)
    for r in rows:
        for field in ('findings', 'full_content_json'):
            val = r.get(field)
            if val is not None and not isinstance(val, str):
                try:
                    r[field] = json.dumps(val, default=str)
                except Exception:
                    r[field] = str(val)
        r['children'] = _to_list(r.get('children'))
    return rows

def print_progress(current, total, operation):
    percent = (current / total) * 100
    bar_length = 50
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    print(f'\r{operation}: |{bar}| {percent:.1f}% ({current}/{total})', end='', flush=True)

def _import_batches(session, label, records, fn, batch_size=1000):
    total = len(records)
    for i in range(0, total, batch_size):
        session.execute_write(fn, records[i:i+batch_size])
        print_progress(min(i + batch_size, total), total, label)
    print()

# --- MAIN EXECUTION ---
def main():
    print("🚀 Starting GraphRAG to Neo4j import process...")

    # Read parquet files
    print("\n📊 Reading parquet files...")
    try:
        entities_df          = pd.read_parquet(f'{OUTPUT_DIR}/entities.parquet')
        relationships_df     = pd.read_parquet(f'{OUTPUT_DIR}/relationships.parquet')
        documents_df         = pd.read_parquet(f'{OUTPUT_DIR}/documents.parquet')
        text_units_df        = pd.read_parquet(f'{OUTPUT_DIR}/text_units.parquet')
        claims_df            = pd.read_parquet(f'{OUTPUT_DIR}/covariates.parquet')
        communities_df       = pd.read_parquet(f'{OUTPUT_DIR}/communities.parquet')
        community_reports_df = pd.read_parquet(f'{OUTPUT_DIR}/community_reports.parquet')
    except FileNotFoundError as e:
        print(f"❌ Could not find parquet files: {e}")
        print("Make sure you've run the GraphRAG indexing process first.")
        sys.exit(1)

    print(f"✅ Found: {len(documents_df)} docs | {len(text_units_df)} text units | "
          f"{len(entities_df)} entities | {len(relationships_df)} relationships | "
          f"{len(claims_df)} claims | {len(communities_df)} communities | "
          f"{len(community_reports_df)} community reports")

    # Prepare records (normalise numpy types and list fields)
    doc_records     = _records(documents_df)
    text_records    = _prep_text_units(text_units_df)
    entity_records  = _records(entities_df)
    rel_records     = _prep_relationships(relationships_df)
    claim_records   = _records(claims_df)
    comm_records    = _prep_communities(communities_df)
    report_records  = _prep_community_reports(community_reports_df)

    driver = create_driver()
    try:
        with driver.session() as session:
            # Indexes first (idempotent)
            print("\n🗂️  Creating indexes...")
            create_indexes(session)
            print("✅ Indexes ready")

            # Clear existing data
            print("\n🗑️  Clearing existing data...")
            session.execute_write(clear_database)
            print("✅ Database cleared")

            # ── NODES ──────────────────────────────────────────────
            print(f"\n📄 Importing {len(doc_records)} documents...")
            _import_batches(session, "Documents", doc_records, create_documents)

            print(f"\n📝 Importing {len(text_records)} text units...")
            _import_batches(session, "TextUnits", text_records, create_text_units)

            print(f"\n👤 Importing {len(entity_records)} entities...")
            _import_batches(session, "Entities", entity_records, create_entity_nodes)

            print(f"\n🏘️  Importing {len(comm_records)} communities...")
            _import_batches(session, "Communities", comm_records, create_communities)

            print(f"\n📋 Importing {len(report_records)} community reports...")
            _import_batches(session, "CommunityReports", report_records, create_community_reports)

            print(f"\n⚖️  Importing {len(claim_records)} claims...")
            _import_batches(session, "Claims", claim_records, create_claims)

            # ── EDGES ──────────────────────────────────────────────
            print("\n🔗 Creating edges...")

            # Entity -[:RELATED]-> Entity  (with text_unit_ids property)
            print(f"   Entity -[:RELATED]-> Entity ({len(rel_records)})...")
            _import_batches(session, "  RELATED", rel_records, create_relationships)

            # Document -[:CONTAINS]-> TextUnit
            session.execute_write(create_document_text_unit_edges, text_records)
            print("   ✅ Document -[:CONTAINS]-> TextUnit")

            # Entity -[:MENTIONED_IN]-> TextUnit
            session.execute_write(create_entity_text_unit_edges, text_records)
            print("   ✅ Entity -[:MENTIONED_IN]-> TextUnit")

            # Claim -[:EXTRACTED_FROM]-> TextUnit
            # Claim -[:ABOUT_SUBJECT]-> Entity
            # Claim -[:ABOUT_OBJECT]->  Entity
            session.execute_write(create_claim_edges, claim_records)
            print("   ✅ Claim -[:EXTRACTED_FROM / ABOUT_SUBJECT / ABOUT_OBJECT]-> ...")

            # Entity -[:BELONGS_TO]-> Community
            session.execute_write(create_entity_community_edges, comm_records)
            print("   ✅ Entity -[:BELONGS_TO]-> Community")

            # Community -[:PARENT_OF]-> Community  (hierarchy)
            session.execute_write(create_community_hierarchy_edges, comm_records)
            print("   ✅ Community -[:PARENT_OF]-> Community")

            # CommunityReport -[:DESCRIBES]-> Community
            session.execute_write(create_community_report_edges, report_records)
            print("   ✅ CommunityReport -[:DESCRIBES]-> Community")

            # ── STATS ──────────────────────────────────────────────
            print("\n📊 Import Statistics:")
            labels = ['Document','TextUnit','Entity','Claim','Community','CommunityReport']
            for lbl in labels:
                n = session.run(f"MATCH (n:{lbl}) RETURN count(n) as c").single()["c"]
                print(f"   {lbl}: {n}")
            total_nodes = session.run("MATCH (n) RETURN count(n) as c").single()["c"]
            total_rels  = session.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
            print(f"   ─────────────────")
            print(f"   Total nodes:         {total_nodes}")
            print(f"   Total relationships: {total_rels}")

            # Edge-type breakdown
            edge_types = session.run("""
                MATCH ()-[r]->() RETURN type(r) AS t, count(r) AS c ORDER BY c DESC
            """).data()
            for row in edge_types:
                print(f"   [{row['t']}]: {row['c']}")

    finally:
        driver.close()

    print("\n🎉 Import completed successfully!")
    print("🌐 Open Neo4j Browser at http://localhost:7474")
    print("\n💡 Example Cypher queries:")
    print("   MATCH (n) RETURN labels(n) AS NodeType, count(n) AS Count ORDER BY Count DESC")
    print("   MATCH (e:Entity)-[r:RELATED]->(e2:Entity) RETURN e.name, r.description, e2.name LIMIT 25")
    print("   MATCH (c:Claim)-[:ABOUT_SUBJECT]->(e:Entity) RETURN e.name, c.type, c.description LIMIT 10")
    print("   MATCH (e:Entity)-[:BELONGS_TO]->(comm:Community)<-[:DESCRIBES]-(cr:CommunityReport)")
    print("         RETURN e.name, comm.title, cr.summary LIMIT 10")
    print("   MATCH p=(root:Community)-[:PARENT_OF*]->(child:Community) RETURN p")
    print(f"   • Entity mentions: MATCH (e:Entity)-[:MENTIONED_IN]->(t:TextUnit) RETURN e, t LIMIT 10")
    print(f"   • Claims about entities: MATCH (c:Claim)-[:ABOUT_SUBJECT]->(e:Entity) RETURN c, e LIMIT 10")
    print(f"   • Community structure: MATCH (e:Entity)-[:BELONGS_TO]->(c:Community)<-[:DESCRIBES]-(cr:CommunityReport) RETURN e, c, cr LIMIT 10")
    print(f"   • Find most connected entities: MATCH (e:Entity) RETURN e.name, e.degree ORDER BY e.degree DESC LIMIT 10")

if __name__ == "__main__":
    main()