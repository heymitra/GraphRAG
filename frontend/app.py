import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask, request, render_template, jsonify, Response
from werkzeug.utils import secure_filename
from neo4j import GraphDatabase
import subprocess
import threading
import shutil
import time

# ── Paths (relative to project root, where the app is launched from) ──────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, 'frontend', 'uploads')
INPUT_FOLDER  = os.path.join(PROJECT_ROOT, 'input')
GRAPHRAG_BIN  = os.path.join(PROJECT_ROOT, 'graphrag-env', 'bin', 'graphrag')
PYTHON_BIN    = os.path.join(PROJECT_ROOT, 'graphrag-env', 'bin', 'python')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(INPUT_FOLDER,  exist_ok=True)

# ── Neo4j ─────────────────────────────────────────────────────────────────────
NEO4J_URI      = "bolt://localhost:7688"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "graphrag123"

def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ── Global pipeline state ─────────────────────────────────────────────────────
pipeline_state = {
    "status": "idle",   # idle | running | done | error
    "stage":  "",
    "log":    [],
    "error":  None,
}
pipeline_lock = threading.Lock()

def _log(msg):
    with pipeline_lock:
        pipeline_state["log"].append(msg)
    print(msg, flush=True)

def _set_stage(stage):
    with pipeline_lock:
        pipeline_state["stage"] = stage
    _log(f"[{stage}]")

def _run_step(cmd, cwd=PROJECT_ROOT):
    """Run a shell command, stream output into the log. Returns True on success."""
    _log(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1
    )
    for line in proc.stdout:
        _log(line.rstrip())
    proc.wait()
    return proc.returncode == 0

def run_full_pipeline(pdf_path, stem):
    """Background thread: extract → clear cache → graphrag index → import neo4j."""
    with pipeline_lock:
        pipeline_state["status"] = "running"
        pipeline_state["stage"]  = ""
        pipeline_state["log"]    = []
        pipeline_state["error"]  = None

    try:
        # 1 ─ Extract PDF text ─────────────────────────────────────────────────
        _set_stage("Extracting PDF text")
        from extract_pdf import extract_pdf_text
        output_txt = os.path.join(INPUT_FOLDER, f"{stem}.txt")
        # Keeps existing input files to run GraphRAG incrementally
        result = extract_pdf_text(pdf_path, output_txt)
        if result is None:
            raise RuntimeError("PDF extraction returned no text.")
        _log(f"Saved extracted text → {output_txt}")

        # 2 ─ GraphRAG Incremental ─────────────────────────────────────────────
        _set_stage("Keeping cache for incremental indexing")
        _log("Cache retained.")

        # 3 ─ Run graphrag index ───────────────────────────────────────────────
        _set_stage("Running GraphRAG indexing (this may take several minutes…)")
        ok = _run_step([GRAPHRAG_BIN, 'index', '--root', PROJECT_ROOT])
        if not ok:
            raise RuntimeError("graphrag index failed – check the log above.")

        # 4 ─ Import to Neo4j ──────────────────────────────────────────────────
        _set_stage("Importing results into Neo4j")
        ok = _run_step([PYTHON_BIN, os.path.join(PROJECT_ROOT, 'import_neo4j.py')])
        if not ok:
            raise RuntimeError("import_neo4j.py failed – check the log above.")

        with pipeline_lock:
            pipeline_state["status"] = "done"
            pipeline_state["stage"]  = "Complete!"
        _log("✅ Pipeline finished. Open http://localhost:7475 to explore the graph.")

    except Exception as exc:
        with pipeline_lock:
            pipeline_state["status"] = "error"
            pipeline_state["stage"]  = "Error"
            pipeline_state["error"]  = str(exc)
        _log(f"❌ Pipeline error: {exc}")

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    if pipeline_state["status"] == "running":
        return jsonify({"error": "A pipeline is already running. Please wait."}), 409
    if 'pdf' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['pdf']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    filename = secure_filename(file.filename)
    stem     = os.path.splitext(filename)[0]
    save_path = os.path.join(UPLOAD_FOLDER, filename)
    file.save(save_path)

    t = threading.Thread(target=run_full_pipeline, args=(save_path, stem), daemon=True)
    t.start()
    return jsonify({"ok": True, "filename": filename})

@app.route('/api/status')
def api_status():
    with pipeline_lock:
        return jsonify({
            "status": pipeline_state["status"],
            "stage":  pipeline_state["stage"],
            "log":    pipeline_state["log"][-100:],   # last 100 lines
            "error":  pipeline_state["error"],
        })

@app.route('/api/data')
def api_data():
    try:
        driver = get_driver()
    except Exception as e:
        return jsonify({"error": str(e)}), 503

    with driver.session() as session:
        documents = session.run(
            "MATCH (d:Document) RETURN d.id AS id, d.title AS title"
        ).data()

        entities = session.run(
            "MATCH (e:Entity) "
            "OPTIONAL MATCH (e)-[:MENTIONED_IN]->(t:TextUnit)<-[:CONTAINS]-(d:Document) "
            "WITH e, collect(DISTINCT d.id) AS document_ids "
            "RETURN e.id AS id, e.name AS name, e.type AS type, "
            "e.description AS description, e.degree AS degree, document_ids "
            "ORDER BY e.degree DESC LIMIT 300"
        ).data()

        claims = session.run(
            "MATCH (c:Claim) "
            "OPTIONAL MATCH (c)-[:ABOUT_SUBJECT]->(subj:Entity) "
            "OPTIONAL MATCH (c)-[:ABOUT_OBJECT]->(obj:Entity) "
            "OPTIONAL MATCH (c)-[:EXTRACTED_FROM]->(t:TextUnit)<-[:CONTAINS]-(d:Document) "
            "RETURN c.id AS id, c.type AS type, c.description AS description, "
            "c.status AS status, subj.name AS subject, obj.name AS object, "
            "d.id AS document_id LIMIT 300"
        ).data()

        communities = session.run(
            "MATCH (comm:Community) "
            "OPTIONAL MATCH (cr:CommunityReport)-[:DESCRIBES]->(comm) "
            "RETURN comm.id AS id, comm.title AS title, comm.level AS level, "
            "comm.size AS size, cr.summary AS summary LIMIT 50"
        ).data()

        comm_entities = session.run(
            "MATCH (comm:Community)<-[:BELONGS_TO]-(e:Entity) "
            "RETURN comm.id AS community_id, "
            "collect({id: e.id, name: e.name, type: e.type}) AS entities"
        ).data()

        relationships = session.run(
            "MATCH (a:Entity)-[r:RELATED]->(b:Entity) "
            "RETURN a.name AS source, b.name AS target, r.description AS description, "
            "r.weight AS weight ORDER BY r.weight DESC LIMIT 100"
        ).data()

        stats = session.run(
            "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count "
            "ORDER BY count DESC"
        ).data()

    driver.close()

    comm_map = {c['community_id']: c['entities'] for c in comm_entities}
    for comm in communities:
        comm['entities'] = comm_map.get(comm['id'], [])

    return jsonify({
        'documents':     documents,
        'entities':      entities,
        'claims':        claims,
        'communities':   communities,
        'relationships': relationships,
        'stats':         stats,
    })

@app.route('/api/clear', methods=['POST'])
def api_clear():
    """Wipe all nodes and relationships from Neo4j."""
    try:
        driver = get_driver()
        with driver.session() as session:
            session.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))
        driver.close()
        # Also clear input files and cache so a future upload starts fresh
        for f in os.listdir(INPUT_FOLDER):
            if f.endswith('.txt'):
                os.remove(os.path.join(INPUT_FOLDER, f))
        cache_dir = os.path.join(PROJECT_ROOT, 'cache')
        if os.path.exists(cache_dir):
            shutil.rmtree(cache_dir)
        return jsonify({"ok": True, "message": "Database cleared."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    """Delete a document from Neo4j and the local filesystem."""
    try:
        driver = get_driver()
        with driver.session() as session:
            # 1. Look up document title to find files
            record = session.run("MATCH (d:Document {id: $doc_id}) RETURN d.title as title", doc_id=doc_id).single()
            if not record:
                return jsonify({"ok": False, "error": "Document not found"}), 404
            
            title = record["title"]
            stem = os.path.splitext(title)[0]
            
            # 2. Delete graph nodes
            session.execute_write(lambda tx: tx.run(
                "MATCH (d:Document {id: $doc_id}) "
                "OPTIONAL MATCH (d)-[:CONTAINS]->(t:TextUnit) "
                "DETACH DELETE d, t", doc_id=doc_id
            ))
            session.execute_write(lambda tx: tx.run("MATCH (c:Claim) WHERE NOT (c)-[:EXTRACTED_FROM]->() DETACH DELETE c"))
            session.execute_write(lambda tx: tx.run("MATCH (e:Entity) WHERE NOT (e)-[:MENTIONED_IN]->() DETACH DELETE e"))
        driver.close()

        # 3. Clean up input files
        txt_path = os.path.join(INPUT_FOLDER, f"{stem}.txt")
        pdf_path = os.path.join(UPLOAD_FOLDER, f"{stem}.pdf")
        if os.path.exists(txt_path):
            os.remove(txt_path)
        if os.path.exists(pdf_path):
            os.remove(pdf_path)

        return jsonify({"ok": True, "message": "Document deleted."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/db_info')
def api_db_info():
    """Return quick node counts so the UI can show current DB state."""
    try:
        driver = get_driver()
        with driver.session() as session:
            rows = session.run(
                "MATCH (n) RETURN labels(n)[0] AS label, count(n) AS count "
                "ORDER BY count DESC"
            ).data()
        driver.close()
        total = sum(r['count'] for r in rows)
        return jsonify({"ok": True, "total": total, "breakdown": rows})
    except Exception as e:
        return jsonify({"ok": False, "total": 0, "breakdown": [], "error": str(e)})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8501, debug=False, use_reloader=False)
