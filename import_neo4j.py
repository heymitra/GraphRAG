import pandas as pd
from neo4j import GraphDatabase
import time
import sys

# --- CONFIGURATION ---
NEO4J_URI = "bolt://localhost:7688"  # or your Aura URI
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "graphrag123"  # Password for Docker Neo4j instance
OUTPUT_DIR = "output"  # Directory where your parquet files are

# --- CONNECT TO NEO4J ---
def create_driver():
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        # Test connection
        with driver.session() as session:
            session.run("RETURN 1")
        print("✅ Successfully connected to Neo4j")
        return driver
    except Exception as e:
        print(f"❌ Failed to connect to Neo4j: {e}")
        print("Please make sure:")
        print("1. Neo4j is running")
        print("2. URI is correct (default: bolt://localhost:7688)")
        print("3. Username and password are correct")
        sys.exit(1)

def clear_database(tx):
    """Clear all nodes and relationships from the database"""
    tx.run("MATCH (n) DETACH DELETE n")

def create_entity_nodes(tx, batch):
    """Create entity nodes with all available properties"""
    query = """
    UNWIND $batch AS row
    MERGE (e:Entity {id: row.id})
    SET e.name = row.title,
        e.type = row.type,
        e.description = row.description,
        e.human_readable_id = row.human_readable_id,
        e.frequency = row.frequency,
        e.degree = row.degree
    """
    tx.run(query, batch=batch)

def create_relationships(tx, batch):
    """Create relationships between entities"""
    query = """
    UNWIND $batch AS row
    MATCH (source:Entity {name: row.source})
    MATCH (target:Entity {name: row.target})
    MERGE (source)-[r:RELATED {id: row.id}]->(target)
    SET r.weight = row.weight,
        r.description = row.description,
        r.human_readable_id = row.human_readable_id,
        r.combined_degree = row.combined_degree
    """
    tx.run(query, batch=batch)

def create_documents(tx, batch):
    """Create document nodes"""
    query = """
    UNWIND $batch AS row
    MERGE (d:Document {id: row.id})
    SET d.title = row.title,
        d.text = row.text,
        d.human_readable_id = row.human_readable_id,
        d.creation_date = row.creation_date
    """
    tx.run(query, batch=batch)

def create_text_units(tx, batch):
    """Create text unit nodes (chunks)"""
    query = """
    UNWIND $batch AS row
    MERGE (t:TextUnit {id: row.id})
    SET t.text = row.text,
        t.n_tokens = row.n_tokens,
        t.human_readable_id = row.human_readable_id
    """
    tx.run(query, batch=batch)

def create_claims(tx, batch):
    """Create claim nodes"""
    query = """
    UNWIND $batch AS row
    MERGE (c:Claim {id: row.id})
    SET c.type = row.type,
        c.description = row.description,
        c.status = row.status,
        c.source_text = row.source_text,
        c.human_readable_id = row.human_readable_id,
        c.start_date = row.start_date,
        c.end_date = row.end_date,
        c.subject_id = row.subject_id,
        c.object_id = row.object_id
    """
    tx.run(query, batch=batch)

def create_communities(tx, batch):
    """Create community nodes"""
    # First create community nodes
    community_query = """
    UNWIND $batch AS row
    MERGE (c:Community {id: row.id})
    SET c.title = row.title,
        c.community = row.community,
        c.level = row.level,
        c.size = row.size,
        c.human_readable_id = row.human_readable_id
    """
    tx.run(community_query, batch=batch)

def create_community_reports(tx, batch):
    """Create community report nodes with full content"""
    query = """
    UNWIND $batch AS row
    MERGE (cr:CommunityReport {id: row.id})
    SET cr.title = row.title,
        cr.summary = row.summary,
        cr.full_content = row.full_content,
        cr.level = row.level,
        cr.rank = row.rank,
        cr.size = row.size,
        cr.human_readable_id = row.human_readable_id
    """
    tx.run(query, batch=batch)

def create_document_relationships(tx, text_units_batch):
    """Link text units to documents"""
    query = """
    UNWIND $batch AS row
    MATCH (t:TextUnit {id: row.id})
    UNWIND row.document_ids as doc_id
    MATCH (d:Document {id: doc_id})
    MERGE (d)-[:CONTAINS]->(t)
    """
    # Only process text units with document IDs (handle numpy arrays)
    units_with_docs = []
    for u in text_units_batch:
        if 'document_ids' in u:
            doc_ids = u['document_ids']
            # Convert numpy array to list if needed
            if hasattr(doc_ids, 'tolist'):
                doc_ids = doc_ids.tolist()
            elif isinstance(doc_ids, str) and doc_ids.startswith('['):
                try:
                    import ast
                    doc_ids = ast.literal_eval(doc_ids)
                except:
                    doc_ids = []
            
            if doc_ids and len(doc_ids) > 0:
                u_copy = u.copy()
                u_copy['document_ids'] = doc_ids
                units_with_docs.append(u_copy)
    
    if units_with_docs:
        tx.run(query, batch=units_with_docs)

def create_entity_text_relationships(tx, text_units_batch):
    """Link entities to text units"""
    query = """
    UNWIND $batch AS row
    MATCH (t:TextUnit {id: row.id})
    UNWIND row.entity_ids as entity_id
    MATCH (e:Entity {id: entity_id})
    MERGE (e)-[:MENTIONED_IN]->(t)
    """
    # Only process text units with entity IDs (handle numpy arrays)
    units_with_entities = []
    for u in text_units_batch:
        if 'entity_ids' in u:
            entity_ids = u['entity_ids']
            # Convert numpy array to list if needed
            if hasattr(entity_ids, 'tolist'):
                entity_ids = entity_ids.tolist()
            elif isinstance(entity_ids, str) and entity_ids.startswith('['):
                try:
                    import ast
                    entity_ids = ast.literal_eval(entity_ids)
                except:
                    entity_ids = []
            
            if entity_ids and len(entity_ids) > 0:
                u_copy = u.copy()
                u_copy['entity_ids'] = entity_ids
                units_with_entities.append(u_copy)
    
    if units_with_entities:
        tx.run(query, batch=units_with_entities)

def create_claim_relationships(tx, claims_batch):
    """Link claims to text units and entities"""
    # Link claims to text units
    text_query = """
    UNWIND $batch AS row
    MATCH (c:Claim {id: row.id})
    MATCH (t:TextUnit {id: row.text_unit_id})
    MERGE (c)-[:EXTRACTED_FROM]->(t)
    """
    claims_with_text = [c for c in claims_batch if 'text_unit_id' in c and c['text_unit_id']]
    if claims_with_text:
        tx.run(text_query, batch=claims_with_text)
    
    # Link claims to subject entities (by entity name)
    subject_query = """
    UNWIND $batch AS row
    MATCH (c:Claim {id: row.id})
    MATCH (e:Entity {name: row.subject_id})
    MERGE (c)-[:ABOUT_SUBJECT]->(e)
    """
    claims_with_subject = [c for c in claims_batch if 'subject_id' in c and c['subject_id'] and c['subject_id'] != 'NONE']
    if claims_with_subject:
        tx.run(subject_query, batch=claims_with_subject)
    
    # Link claims to object entities (by entity name)
    object_query = """
    UNWIND $batch AS row
    MATCH (c:Claim {id: row.id})
    MATCH (e:Entity {name: row.object_id})
    MERGE (c)-[:ABOUT_OBJECT]->(e)
    """
    claims_with_object = [c for c in claims_batch if 'object_id' in c and c['object_id'] and c['object_id'] != 'NONE']
    if claims_with_object:
        tx.run(object_query, batch=claims_with_object)

def link_entities_to_communities(tx, communities_batch):
    """Link entities to their communities using community entity_ids"""
    print(f"    🔍 Processing {len(communities_batch)} communities for entity linking...")
    
    query = """
    UNWIND $batch AS row
    MATCH (c:Community {id: row.id})
    UNWIND row.entity_ids as entity_id
    MATCH (e:Entity {id: entity_id})
    MERGE (e)-[:BELONGS_TO]->(c)
    """
    # Process communities that have entity IDs
    communities_with_entities = []
    for c in communities_batch:
        if 'entity_ids' in c:
            entity_ids = c['entity_ids']
            # Convert numpy array to list if needed
            if hasattr(entity_ids, 'tolist'):
                entity_ids = entity_ids.tolist()
            
            if entity_ids and len(entity_ids) > 0:
                c_copy = c.copy()
                c_copy['entity_ids'] = entity_ids
                communities_with_entities.append(c_copy)
                print(f"    📝 Community {c['id']}: {len(entity_ids)} entities")
    
    if communities_with_entities:
        print(f"    🔗 Creating {sum(len(c['entity_ids']) for c in communities_with_entities)} entity-community relationships...")
        result = tx.run(query, batch=communities_with_entities)
        print(f"    ✅ Created BELONGS_TO relationships")
    else:
        print(f"    ⚠️  No communities with entities found!")

def link_community_reports(tx, community_reports_batch):
    """Link community reports to their communities"""
    print(f"    🔍 Processing {len(community_reports_batch)} community reports for linking...")
    
    query = """
    UNWIND $batch AS row
    MATCH (cr:CommunityReport {id: row.id})
    MATCH (c:Community {community: row.community})
    MERGE (cr)-[:DESCRIBES]->(c)
    """
    result = tx.run(query, batch=community_reports_batch)
    print(f"    ✅ Created DESCRIBES relationships for {len(community_reports_batch)} reports")

def print_progress(current, total, operation):
    """Print progress bar"""
    percent = (current / total) * 100
    bar_length = 50
    filled_length = int(bar_length * current // total)
    bar = '█' * filled_length + '-' * (bar_length - filled_length)
    print(f'\r{operation}: |{bar}| {percent:.1f}% ({current}/{total})', end='', flush=True)

# --- MAIN EXECUTION ---
def main():
    print("🚀 Starting GraphRAG to Neo4j import process...")
    
    # Check if Neo4j driver is installed
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("❌ Neo4j driver not installed. Please run:")
        print("pip install neo4j")
        sys.exit(1)
    
    # Read parquet files
    print("\n📊 Reading parquet files...")
    data_files = {}
    try:
        # Core GraphRAG outputs
        data_files['entities'] = pd.read_parquet(f'{OUTPUT_DIR}/entities.parquet')
        data_files['relationships'] = pd.read_parquet(f'{OUTPUT_DIR}/relationships.parquet')
        data_files['documents'] = pd.read_parquet(f'{OUTPUT_DIR}/documents.parquet')
        data_files['text_units'] = pd.read_parquet(f'{OUTPUT_DIR}/text_units.parquet')
        data_files['claims'] = pd.read_parquet(f'{OUTPUT_DIR}/covariates.parquet')
        data_files['communities'] = pd.read_parquet(f'{OUTPUT_DIR}/communities.parquet')
        data_files['community_reports'] = pd.read_parquet(f'{OUTPUT_DIR}/community_reports.parquet')
        
        print(f"✅ Found:")
        print(f"   📄 {len(data_files['documents'])} documents")
        print(f"   📝 {len(data_files['text_units'])} text units")
        print(f"   👤 {len(data_files['entities'])} entities")
        print(f"   🔗 {len(data_files['relationships'])} relationships")
        print(f"   ⚖️  {len(data_files['claims'])} claims")
        print(f"   🏘️  {len(data_files['communities'])} communities")
        print(f"   📋 {len(data_files['community_reports'])} community reports")
        
    except FileNotFoundError as e:
        print(f"❌ Could not find parquet files: {e}")
        print("Make sure you've run the GraphRAG indexing process first")
        sys.exit(1)
    
    # Display data preview
    print(f"\n📋 Data Preview:")
    print(f"   • Entities columns: {list(data_files['entities'].columns)}")
    print(f"   • Relationships columns: {list(data_files['relationships'].columns)}")
    print(f"   • Documents columns: {list(data_files['documents'].columns)}")
    print(f"   • Text units columns: {list(data_files['text_units'].columns)}")
    print(f"   • Claims columns: {list(data_files['claims'].columns)}")
    print(f"   • Communities columns: {list(data_files['communities'].columns)}")
    print(f"   • Community reports columns: {list(data_files['community_reports'].columns)}")
    
    # Connect to Neo4j
    driver = create_driver()
    
    try:
        with driver.session() as session:
            # Clear existing data
            print(f"\n🗑️  Clearing existing data...")
            session.execute_write(clear_database)
            print("✅ Database cleared")
            
            batch_size = 1000
            
            # Import documents
            print(f"\n📄 Importing {len(data_files['documents'])} documents...")
            doc_records = data_files['documents'].fillna('').to_dict('records')
            for i in range(0, len(doc_records), batch_size):
                batch = doc_records[i:i+batch_size]
                session.execute_write(create_documents, batch)
                print_progress(min(i + batch_size, len(doc_records)), len(doc_records), "Documents")
            print(f"\n✅ Documents imported successfully")
            
            # Import text units
            print(f"\n📝 Importing {len(data_files['text_units'])} text units...")
            text_records = data_files['text_units'].fillna('').to_dict('records')
            for i in range(0, len(text_records), batch_size):
                batch = text_records[i:i+batch_size]
                session.execute_write(create_text_units, batch)
                print_progress(min(i + batch_size, len(text_records)), len(text_records), "Text Units")
            print(f"\n✅ Text units imported successfully")
            
            # Import entities
            print(f"\n👤 Importing {len(data_files['entities'])} entities...")
            entity_records = data_files['entities'].fillna('').to_dict('records')
            for i in range(0, len(entity_records), batch_size):
                batch = entity_records[i:i+batch_size]
                session.execute_write(create_entity_nodes, batch)
                print_progress(min(i + batch_size, len(entity_records)), len(entity_records), "Entities")
            print(f"\n✅ Entities imported successfully")
            
            # Import relationships
            print(f"\n🔗 Importing {len(data_files['relationships'])} relationships...")
            rel_records = data_files['relationships'].fillna('').to_dict('records')
            for i in range(0, len(rel_records), batch_size):
                batch = rel_records[i:i+batch_size]
                session.execute_write(create_relationships, batch)
                print_progress(min(i + batch_size, len(rel_records)), len(rel_records), "Relationships")
            print(f"\n✅ Relationships imported successfully")
            
            # Import claims
            print(f"\n⚖️  Importing {len(data_files['claims'])} claims...")
            claim_records = data_files['claims'].fillna('').to_dict('records')
            for i in range(0, len(claim_records), batch_size):
                batch = claim_records[i:i+batch_size]
                session.execute_write(create_claims, batch)
                print_progress(min(i + batch_size, len(claim_records)), len(claim_records), "Claims")
            print(f"\n✅ Claims imported successfully")
            
            # Import communities
            print(f"\n🏘️  Importing {len(data_files['communities'])} communities...")
            community_records = data_files['communities'].fillna('').to_dict('records')
            for i in range(0, len(community_records), batch_size):
                batch = community_records[i:i+batch_size]
                session.execute_write(create_communities, batch)
                print_progress(min(i + batch_size, len(community_records)), len(community_records), "Communities")
            print(f"\n✅ Communities imported successfully")
            
            # Import community reports
            print(f"\n📋 Importing {len(data_files['community_reports'])} community reports...")
            report_records = data_files['community_reports'].fillna('').to_dict('records')
            for i in range(0, len(report_records), batch_size):
                batch = report_records[i:i+batch_size]
                session.execute_write(create_community_reports, batch)
                print_progress(min(i + batch_size, len(report_records)), len(report_records), "Community Reports")
            print(f"\n✅ Community reports imported successfully")
            
            # Create relationships between different node types
            print(f"\n🔗 Creating relationships...")
            
            # Link documents to text units
            session.execute_write(create_document_relationships, text_records)
            print("   ✅ Document → TextUnit relationships")
            
            # Link entities to text units
            session.execute_write(create_entity_text_relationships, text_records)
            print("   ✅ Entity → TextUnit relationships")
            
            # Link claims to text units and entities
            session.execute_write(create_claim_relationships, claim_records)
            print("   ✅ Claim relationships")
            
            # Link entities to communities (using community entity_ids)
            session.execute_write(link_entities_to_communities, community_records)
            print("   ✅ Entity → Community relationships")
            
            # Link community reports to communities
            session.execute_write(link_community_reports, report_records)
            print("   ✅ CommunityReport → Community relationships")
            
            print(f"\n✅ All relationships created successfully")
            
            # Display comprehensive statistics
            print(f"\n📊 Import Statistics:")
            node_count = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]
            
            # Count each node type
            document_count = session.run("MATCH (n:Document) RETURN count(n) as count").single()["count"]
            text_unit_count = session.run("MATCH (n:TextUnit) RETURN count(n) as count").single()["count"]
            entity_count = session.run("MATCH (n:Entity) RETURN count(n) as count").single()["count"]
            claim_count = session.run("MATCH (n:Claim) RETURN count(n) as count").single()["count"]
            community_count = session.run("MATCH (n:Community) RETURN count(n) as count").single()["count"]
            report_count = session.run("MATCH (n:CommunityReport) RETURN count(n) as count").single()["count"]
            
            print(f"   📊 Total nodes: {node_count}")
            print(f"   🔗 Total relationships: {rel_count}")
            print(f"   📄 Documents: {document_count}")
            print(f"   📝 Text units: {text_unit_count}")
            print(f"   👤 Entities: {entity_count}")
            print(f"   ⚖️  Claims: {claim_count}")
            print(f"   🏘️  Communities: {community_count}")
            print(f"   📋 Community reports: {report_count}")
    
    finally:
        driver.close()
    
    print(f"\n🎉 Import completed successfully!")
    print(f"🌐 Open Neo4j Browser at http://localhost:7475 to explore your graph")
    print(f"\n💡 Useful Cypher queries to get started:")
    print(f"   • View all node types: MATCH (n) RETURN labels(n) as NodeTypes, count(n) as Count ORDER BY Count DESC")
    print(f"   • View documents: MATCH (d:Document) RETURN d LIMIT 10")
    print(f"   • View text chunks: MATCH (t:TextUnit) RETURN t LIMIT 10") 
    print(f"   • View all entities: MATCH (n:Entity) RETURN n LIMIT 25")
    print(f"   • View entity relationships: MATCH (e:Entity)-[r:RELATED]->(e2:Entity) RETURN e, r, e2 LIMIT 25")
    print(f"   • View claims: MATCH (c:Claim) RETURN c LIMIT 10")
    print(f"   • View communities: MATCH (c:Community) RETURN c")
    print(f"   • Document structure: MATCH (d:Document)-[:CONTAINS]->(t:TextUnit) RETURN d, t LIMIT 10")
    print(f"   • Entity mentions: MATCH (e:Entity)-[:MENTIONED_IN]->(t:TextUnit) RETURN e, t LIMIT 10")
    print(f"   • Claims about entities: MATCH (c:Claim)-[:ABOUT_SUBJECT]->(e:Entity) RETURN c, e LIMIT 10")
    print(f"   • Community structure: MATCH (e:Entity)-[:BELONGS_TO]->(c:Community)<-[:DESCRIBES]-(cr:CommunityReport) RETURN e, c, cr LIMIT 10")
    print(f"   • Find most connected entities: MATCH (e:Entity) RETURN e.name, e.degree ORDER BY e.degree DESC LIMIT 10")

if __name__ == "__main__":
    main()