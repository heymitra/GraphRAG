# GraphRAG Neo4j Integration Project

This project demonstrates how to use Microsoft GraphRAG to extract knowledge graphs from PDF documents and visualize them in Neo4j.

## Features

- **PDF Document Processing**: Extract text from PDF files and process with GraphRAG
- **Knowledge Graph Extraction**: Use GraphRAG to identify entities, relationships, and claims
- **Neo4j Visualization**: Import complete GraphRAG data into Neo4j for interactive exploration
- **Jupyter Analysis**: Interactive notebooks for data exploration and visualization

## Project Structure

```
├── settings.yaml              # GraphRAG configuration
├── prompts/                   # Custom GraphRAG prompts
├── input/                     # Input documents (excluded from git)
├── import_neo4j.py           # Neo4j import script
├── inspect.ipynb             # Jupyter notebook for analysis
├── update_graph.sh           # Automated update workflow
├── extract_pdf.py            # PDF text extraction utility
└── analyze_claims.py         # Claims analysis script
```

## Setup

### 1. Create Virtual Environment
```bash
python -m venv graphrag-env
source graphrag-env/bin/activate  # On Windows: graphrag-env\Scripts\activate
```

### 2. Install Dependencies
```bash
pip install graphrag neo4j pandas jupyter matplotlib networkx PyPDF2
```

### 3. Configure Environment
Create `.env` file with your API keys:
```
GRAPHRAG_API_KEY=your_openai_api_key
GRAPHRAG_API_BASE=https://api.openai.com/v1
```

### 4. Setup Neo4j
Run Neo4j with Docker:
```bash
docker run -d \
  --name graphrag-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/graphrag123 \
  neo4j:latest
```

## Usage

### 1. Add Documents
Place your PDF documents in the `input/` directory or use the PDF extraction script:
```bash
python extract_pdf.py
```

### 2. Process with GraphRAG
```bash
# Run the complete workflow
./update_graph.sh

# Or run steps manually:
graphrag index                    # Extract knowledge graph
python import_neo4j.py           # Import to Neo4j
```

### 3. Explore the Graph
- **Neo4j Browser**: Open http://localhost:7474
- **Jupyter Notebook**: Run `inspect.ipynb` for interactive analysis

## Key Cypher Queries

```cypher
-- View all entities
MATCH (e:Entity) RETURN e.name, e.type, e.description LIMIT 25

-- Find relationships
MATCH (e:Entity)-[r:RELATED]->(e2:Entity) 
RETURN e.name, r.description, e2.name LIMIT 25

-- Explore claims about entities
MATCH (c:Claim)-[:ABOUT_SUBJECT]->(e:Entity) 
RETURN e.name, c.type, c.description LIMIT 10

-- Community structure
MATCH (e:Entity)-[:BELONGS_TO]->(comm:Community)<-[:DESCRIBES]-(report:CommunityReport)
RETURN e.name, comm.title, report.summary LIMIT 10
```

## Configuration

Key settings in `settings.yaml`:
- **LLM Model**: gpt-4o-mini for cost efficiency
- **Chunk Size**: 3000 tokens for comprehensive context
- **Entity Types**: organization, person, geo, event, product, technology
- **Max Gleanings**: 2 for thorough extraction

## Data Flow

1. **Input**: PDF documents → Text extraction
2. **GraphRAG**: Text → Entities, Relationships, Claims, Communities
3. **Neo4j**: Structured import with proper relationships
4. **Visualization**: Interactive graph exploration

## Architecture Notes

- **Claims/Covariates** are properly linked to entities as subject/object relationships
- **Communities** represent topic clusters with entity membership
- **Text Units** maintain document structure and entity mentions
- **Embeddings** enable semantic search capabilities

## Troubleshooting

### Common Issues
- **Authentication**: Ensure Neo4j password matches in import script
- **Port Conflicts**: Check Neo4j ports (7474/7687) aren't already in use
- **API Limits**: Monitor OpenAI API usage and rate limits
- **Memory**: Large documents may require increasing chunk sizes

### File Synchronization
If GraphRAG processes old content:
```bash
rm -rf cache/  # Clear GraphRAG cache
```

## Contributing

1. Follow the existing code structure
2. Update documentation for new features
3. Test with both small and large documents
4. Ensure proper .gitignore exclusions

## License

This project is for educational and research purposes.