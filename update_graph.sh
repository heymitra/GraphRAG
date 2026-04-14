#!/bin/bash

# GraphRAG Update Script
# Run this after adding/modifying documents in input/

echo "🚀 Starting GraphRAG update process..."

# Clear cache to ensure fresh processing
echo "🗑️ Clearing cache..."
rm -rf cache/

# Activate virtual environment and run indexing
echo "📊 Re-indexing with GraphRAG..."
source graphrag-env/bin/activate
python -m graphrag index

if [ $? -eq 0 ]; then
    echo "✅ GraphRAG indexing completed"
    
    # Re-import to Neo4j
    echo "🔄 Updating Neo4j database..."
    python import_neo4j.py
    
    if [ $? -eq 0 ]; then
        echo "✅ Neo4j updated successfully"
        echo "🌐 Open Neo4j Browser: http://localhost:7474"
        echo "📊 Or run Jupyter cells in inspect.ipynb"
    else
        echo "❌ Neo4j import failed"
    fi
else
    echo "❌ GraphRAG indexing failed"
fi
