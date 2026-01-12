#!/usr/bin/env python3

from neo4j import GraphDatabase

def debug_entity_names():
    """Check entity names to see if they match claim subject/object IDs"""
    driver = GraphDatabase.driver('bolt://localhost:7688', auth=('neo4j', 'graphrag123'))
    
    with driver.session() as session:
        # Get all entity names (not titles)
        result = session.run('MATCH (e:Entity) RETURN e.name ORDER BY e.name')
        entity_names = [record["e.name"] for record in result]
        
        print("=== Entity Names in Neo4j ===")
        for name in entity_names:
            print(f"'{name}'")
        
        # Get all claims with their subject/object IDs
        result = session.run('MATCH (c:Claim) RETURN c.subject_id, c.object_id, c.type')
        
        print("\n=== Claims Subject/Object IDs ===")
        for record in result:
            subject = record["c.subject_id"]
            object_id = record["c.object_id"] 
            claim_type = record["c.type"]
            
            subject_match = subject in entity_names if subject else False
            object_match = object_id in entity_names if object_id and object_id != 'NONE' else False
            
            print(f"{claim_type}:")
            print(f"  subject_id: '{subject}' - Match: {subject_match}")
            if object_id and object_id != 'NONE':
                print(f"  object_id: '{object_id}' - Match: {object_match}")
            print()
    
    driver.close()

if __name__ == "__main__":
    debug_entity_names()