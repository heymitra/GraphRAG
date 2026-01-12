#!/usr/bin/env python3

import pandas as pd
import json

def analyze_claims():
    """Analyze the claims data structure"""
    try:
        # Load claims data (called covariates in GraphRAG)
        claims_df = pd.read_parquet('output/covariates.parquet')
        
        print(f"Claims DataFrame shape: {claims_df.shape}")
        print(f"Columns: {list(claims_df.columns)}")
        print()
        
        # Check subject_id and object_id
        for col in ['subject_id', 'object_id']:
            if col in claims_df.columns:
                non_null_count = claims_df[col].notna().sum()
                print(f"{col}: {non_null_count}/{len(claims_df)} non-null values")
                if non_null_count > 0:
                    sample_values = claims_df[col].dropna().head(3).tolist()
                    print(f"  Sample values: {sample_values}")
                else:
                    print(f"  All values are null/empty")
            else:
                print(f"{col}: Column not found")
        
        print("\n" + "="*50)
        print("Sample Claims:")
        for i in range(min(3, len(claims_df))):
            claim = claims_df.iloc[i].to_dict()
            print(f"\nClaim {i+1}:")
            for key, value in claim.items():
                if pd.notna(value):
                    print(f"  {key}: {value}")
        
        # Check if subject_id and object_id have valid entity references
        print("\n" + "="*50)
        print("Entity ID Analysis:")
        
        # Load entities to compare
        entities_df = pd.read_parquet('output/entities.parquet')
        entity_ids = set(entities_df['id'].tolist())
        print(f"Total entities in graph: {len(entity_ids)}")
        
        for col in ['subject_id', 'object_id']:
            if col in claims_df.columns and claims_df[col].notna().sum() > 0:
                claim_entity_ids = set(claims_df[col].dropna().tolist())
                matching_ids = claim_entity_ids.intersection(entity_ids)
                print(f"{col}: {len(matching_ids)}/{len(claim_entity_ids)} match actual entity IDs")
                if len(matching_ids) > 0:
                    print(f"  Matching IDs: {list(matching_ids)[:3]}")
        
    except Exception as e:
        print(f"Error analyzing claims: {e}")

if __name__ == "__main__":
    analyze_claims()