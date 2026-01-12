#!/usr/bin/env python3

from neo4j import GraphDatabase

def check_claim_relationships():
    """Check if claims are properly linked to entities"""
    driver = GraphDatabase.driver('bolt://localhost:7688', auth=('neo4j', 'graphrag123'))
    
    with driver.session() as session:
        # Check claim-entity relationships
        result = session.run('''
            MATCH (c:Claim)-[r]->(e:Entity)
            RETURN c.type, c.description, type(r) as rel_type, e.title
            ORDER BY c.type
        ''')
        
        print('=== Claims linked to Entities ===')
        records = list(result)
        for record in records:
            print(f'{record["c.type"]}: {record["c.description"][:80]}...')
            print(f'  -> {record["rel_type"]}: {record["e.title"]}')
            print()
        
        if not records:
            print("No claim-entity relationships found!")
        
        # Count relationships by type
        result = session.run('''
            MATCH (c:Claim)-[r:ABOUT_SUBJECT]->(e:Entity)
            RETURN count(*) as subject_rels
        ''')
        subject_count = result.single()[0]
        
        result = session.run('''
            MATCH (c:Claim)-[r:ABOUT_OBJECT]->(e:Entity)
            RETURN count(*) as object_rels
        ''')
        object_count = result.single()[0]
        
        print(f'Claim-Entity relationships created:')
        print(f'  ABOUT_SUBJECT: {subject_count}')
        print(f'  ABOUT_OBJECT: {object_count}')
        
        # Show a specific entity with its claims
        result = session.run('''
            MATCH (e:Entity {title: "ALBERTO STASI"})<-[r]-(c:Claim)
            RETURN e.title, c.type, c.description, type(r) as rel_type
            ORDER BY c.type
        ''')
        
        print(f'\\n=== Claims about ALBERTO STASI ===')
        for record in result:
            print(f'{record["c.type"]}: {record["c.description"][:100]}...')
            print(f'  Relationship: {record["rel_type"]}')
            print()
    
    driver.close()

if __name__ == "__main__":
    check_claim_relationships()