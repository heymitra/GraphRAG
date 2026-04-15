import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from flask import Flask, request, render_template, jsonify, Response
from werkzeug.utils import secure_filename
from neo4j import GraphDatabase
import subprocess
import threading
import shutil
import time
import math
import json as _json

import networkx as nx
import pandas as pd
from graphrag_runtime import find_missing_prompt_paths, stage_runtime_config

# ── Paths (relative to project root, where the app is launched from) ──────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_REQUEST = os.getenv('GRAPHRAG_CONFIG', 'settings.yaml')
OUTPUT_OVERRIDE = os.getenv('GRAPHRAG_OUTPUT_DIR')
CACHE_OVERRIDE = os.getenv('GRAPHRAG_CACHE_DIR')
RUNTIME_INFO = stage_runtime_config(
    CONFIG_REQUEST,
    output_override=OUTPUT_OVERRIDE,
    cache_override=CACHE_OVERRIDE,
)
GRAPHRAG_CONFIG = RUNTIME_INFO.config_path
RUNTIME_ROOT = RUNTIME_INFO.runtime_root
OUTPUT_FOLDER = RUNTIME_INFO.output_dir
CACHE_FOLDER = RUNTIME_INFO.cache_dir
UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, 'frontend', 'uploads')
INPUT_FOLDER  = os.path.join(PROJECT_ROOT, 'input')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(INPUT_FOLDER,  exist_ok=True)

def _resolve_python_bin():
    """Prefer the project venv, but fall back to the current interpreter."""
    candidates = [
        os.path.join(PROJECT_ROOT, 'graphrag-env', 'bin', 'python'),
        sys.executable,
        shutil.which('python3'),
        shutil.which('python'),
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return candidate
    raise RuntimeError("Unable to locate a Python interpreter for GraphRAG.")

PYTHON_BIN = _resolve_python_bin()
GRAPHRAG_CMD = [PYTHON_BIN, '-m', 'graphrag']

# ── Neo4j (used only for write/admin operations) ──────────────────────────────
NEO4J_URI      = "bolt://localhost:7688"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "graphrag123"

def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ── Parquet helpers ───────────────────────────────────────────────────────────
def _parquet(filename):
    """Read a parquet from output/; return empty DataFrame if missing."""
    path = os.path.join(OUTPUT_FOLDER, filename)
    try:
        return pd.read_parquet(path)
    except (FileNotFoundError, OSError):
        return pd.DataFrame()

def _to_list(val):
    """Normalise numpy arrays / None / strings-that-look-like-lists to Python lists."""
    if val is None:
        return []
    if hasattr(val, 'tolist'):
        return [v for v in val.tolist() if v is not None]
    if isinstance(val, list):
        return [v for v in val if v is not None]
    if isinstance(val, str) and val.startswith('['):
        try:
            return [v for v in _json.loads(val) if v is not None]
        except Exception:
            return []
    return []

def _clean_type(val):
    """Strip LLM extraction artifacts (e.g. '<|diff_marker|>…') from type strings."""
    if not val:
        return ''
    return str(val).split('<')[0].strip()

def _build_layout_positions(ents_df, rels_df):
    """Use saved coordinates when present, otherwise derive a stable spring layout."""
    positions = {}
    graph = nx.Graph()
    has_saved_layout = True

    for _, row in ents_df.iterrows():
        name = row.get('title', '') or ''
        if not name:
            continue
        graph.add_node(name)
        try:
            x = float(row.get('x'))
            y = float(row.get('y'))
            if math.isnan(x) or math.isnan(y):
                raise ValueError
            positions[name] = (x, y)
        except (TypeError, ValueError):
            has_saved_layout = False

    for _, row in rels_df.iterrows():
        src = row.get('source', '') or ''
        tgt = row.get('target', '') or ''
        if not src or not tgt:
            continue
        try:
            weight = float(row.get('weight', 1.0) or 1.0)
        except (TypeError, ValueError):
            weight = 1.0
        graph.add_edge(src, tgt, weight=weight)

    if graph.number_of_nodes() == 0:
        return {}

    if has_saved_layout and positions:
        return positions

    if graph.number_of_edges() == 0:
        names = list(graph.nodes())
        total = max(len(names), 1)
        return {
            name: (
                math.cos((2 * math.pi * idx) / total),
                math.sin((2 * math.pi * idx) / total),
            )
            for idx, name in enumerate(names)
        }

    return {
        name: (float(coords[0]), float(coords[1]))
        for name, coords in nx.spring_layout(graph, seed=42, weight='weight').items()
    }


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

def _run_step(cmd, cwd=PROJECT_ROOT, env=None):
    """Run a shell command, stream output into the log. Returns True on success."""
    _log(f"$ {' '.join(cmd)}")
    proc = subprocess.Popen(
        cmd, cwd=cwd,
        env=env,
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
        _log(f"Using GraphRAG config → {os.path.relpath(GRAPHRAG_CONFIG, PROJECT_ROOT)}")
        _log(f"Using GraphRAG runtime root → {os.path.relpath(RUNTIME_ROOT, PROJECT_ROOT)}")
        _log(f"Using GraphRAG output → {os.path.relpath(OUTPUT_FOLDER, PROJECT_ROOT)}")

        missing_prompts = find_missing_prompt_paths(GRAPHRAG_CONFIG)
        if missing_prompts:
            missing_text = "\n".join(f" - {path}" for path in missing_prompts)
            raise RuntimeError(
                "The active GraphRAG config references prompt files that do not exist.\n"
                f"{missing_text}\n"
                'Run `DOMAIN="your corpus domain" ./auto_tune.sh` before using '
                "`settings.auto.yaml` for indexing."
            )

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
        index_cmd = GRAPHRAG_CMD + ['index', '--root', RUNTIME_ROOT]
        ok = _run_step(index_cmd)
        if not ok:
            raise RuntimeError("graphrag index failed – check the log above.")

        # 4 ─ Import to Neo4j ──────────────────────────────────────────────────
        _set_stage("Importing results into Neo4j")
        import_env = dict(os.environ)
        import_env['OUTPUT_DIR'] = OUTPUT_FOLDER
        ok = _run_step(
            [PYTHON_BIN, os.path.join(PROJECT_ROOT, 'import_neo4j.py')],
            env=import_env,
        )
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
    missing_prompts = find_missing_prompt_paths(GRAPHRAG_CONFIG)
    if missing_prompts:
        return jsonify({
            "error": (
                "The active GraphRAG config is missing prompt files. "
                'Run `DOMAIN="your corpus domain" ./auto_tune.sh` before using '
                "`settings.auto.yaml`."
            ),
            "missing_prompts": missing_prompts,
        }), 400
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
    """Return all graph data read directly from parquet pipeline output."""
    docs_df  = _parquet('documents.parquet')
    ents_df  = _parquet('entities.parquet')
    rels_df  = _parquet('relationships.parquet')
    comms_df = _parquet('communities.parquet')
    crs_df   = _parquet('community_reports.parquet')
    tu_df    = _parquet('text_units.parquet')
    cov_df   = _parquet('covariates.parquet')

    if docs_df.empty and ents_df.empty:
        return jsonify({'documents': [], 'entities': [], 'claims': [],
                        'communities': [], 'relationships': [], 'stats': []})

    # ── Documents ────────────────────────────────────────────────────────────
    documents = [
        {'id': str(r['id']), 'title': r.get('title', '') or ''}
        for _, r in docs_df.iterrows()
    ]

    # ── text_unit_id → [document_ids] lookup ─────────────────────────────────
    tu_to_docs = {}
    for _, row in tu_df.iterrows():
        doc_ids = _to_list(row.get('document_ids'))
        if doc_ids:
            tu_to_docs[str(row['id'])] = doc_ids
    tu_to_first_doc = {k: v[0] for k, v in tu_to_docs.items()}

    # ── Entities ─────────────────────────────────────────────────────────────
    entities = []
    for _, row in ents_df.iterrows():
        doc_ids = []
        for tu_id in _to_list(row.get('text_unit_ids')):
            for did in tu_to_docs.get(str(tu_id), []):
                if did not in doc_ids:
                    doc_ids.append(did)
        entities.append({
            'id':          str(row['id']),
            'name':        row.get('title', '') or '',
            'type':        (row.get('type', '') or '').lower(),
            'description': row.get('description', '') or '',
            'degree':      int(row.get('degree', 0) or 0),
            'frequency':   int(row.get('frequency', 0) or 0),
            'document_ids': doc_ids,
        })
    entities.sort(key=lambda x: x['degree'], reverse=True)
    entities = entities[:300]

    # ── Claims / Covariates ───────────────────────────────────────────────────
    claims = []
    for _, row in cov_df.iterrows():
        tu_id = str(row.get('text_unit_id', '') or '')
        raw_start = str(row.get('start_date', '') or '')
        raw_end   = str(row.get('end_date',   '') or '')
        claims.append({
            'id':          str(row['id']),
            'type':        _clean_type(row.get('type', '') or ''),
            'description': row.get('description', '') or '',
            'status':      row.get('status', '') or '',
            'subject':     row.get('subject_id', '') or '',
            'object':      row.get('object_id', '') or '',
            'start_date':  raw_start[:10] if raw_start not in ('', 'nan', 'None') else '',
            'end_date':    raw_end[:10]   if raw_end   not in ('', 'nan', 'None') else '',
            'document_id': tu_to_first_doc.get(tu_id),
        })
    claims = claims[:300]

    # ── Communities ───────────────────────────────────────────────────────────
    # community_reports has AI titles + summaries; communities has entity_ids
    # join on the shared 'community' integer key
    ent_lookup = {
        str(r['id']): {'id': str(r['id']),
                       'name': r.get('title', '') or '',
                       'type': (r.get('type', '') or '').lower()}
        for _, r in ents_df.iterrows()
    }
    comm_num_to_eids  = {}
    comm_num_to_title = {}   # structural title from communities.parquet ("Community N")
    for _, row in comms_df.iterrows():
        num = row.get('community')
        if num is not None:
            n = int(num)
            comm_num_to_eids[n]  = _to_list(row.get('entity_ids'))
            comm_num_to_title[n] = row.get('title', '') or f'Community {n}'

    communities = []
    for _, row in crs_df.iterrows():
        num      = row.get('community')
        comm_num = int(num) if num is not None else -1
        eids     = comm_num_to_eids.get(comm_num, [])
        base     = comm_num_to_title.get(comm_num, f'Community {comm_num}')
        raw_findings = row.get('findings')
        findings_count = len(raw_findings) if isinstance(raw_findings, list) else 0
        communities.append({
            'id':             str(row['id']),
            'community_num':  comm_num,
            'base_title':     base,
            'report_title':   row.get('title', '') or '',
            'level':          int(row.get('level', 0) or 0),
            'rank':           float(row.get('rank', 0) or 0),
            'findings_count': findings_count,
            'summary':        row.get('summary', '') or '',
            'entities':       [ent_lookup[e] for e in eids if e in ent_lookup],
        })
    communities = sorted(communities, key=lambda c: c['rank'], reverse=True)

    # ── Relationships ─────────────────────────────────────────────────────────
    relationships = []
    for _, row in rels_df.iterrows():
        relationships.append({
            'source':      row.get('source', '') or '',
            'target':      row.get('target', '') or '',
            'description': row.get('description', '') or '',
            'weight':      float(row.get('weight', 1.0) or 1.0),
        })
    relationships.sort(key=lambda x: x['weight'], reverse=True)
    relationships = relationships[:100]

    # ── Stats ─────────────────────────────────────────────────────────────────
    stats = [
        {'label': 'Document',     'count': len(docs_df)},
        {'label': 'Entity',       'count': len(ents_df)},
        {'label': 'Relationship', 'count': len(rels_df)},
        {'label': 'Community',    'count': len(crs_df)},
        {'label': 'TextUnit',     'count': len(tu_df)},
        {'label': 'Claim',        'count': len(cov_df)},
    ]

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
    """Wipe pipeline output, input files, and cache. Also clears Neo4j if reachable."""
    errors = []

    # 1. Clear Neo4j (best-effort — might not be running)
    try:
        driver = get_driver()
        with driver.session() as session:
            session.execute_write(lambda tx: tx.run("MATCH (n) DETACH DELETE n"))
        driver.close()
    except Exception as e:
        errors.append(f"Neo4j: {e}")

    # 2. Clear input files
    for f in os.listdir(INPUT_FOLDER):
        if f.endswith('.txt'):
            os.remove(os.path.join(INPUT_FOLDER, f))

    # 3. Remove pipeline output (parquet files)
    if os.path.exists(OUTPUT_FOLDER):
        shutil.rmtree(OUTPUT_FOLDER)

    # 4. Clear GraphRAG cache
    if os.path.exists(CACHE_FOLDER):
        shutil.rmtree(CACHE_FOLDER)

    msg = "Cleared." + (f" (warnings: {'; '.join(errors)})" if errors else "")
    return jsonify({"ok": True, "message": msg})


@app.route('/api/documents/<doc_id>', methods=['DELETE'])
def delete_document(doc_id):
    """Remove a document's input file. Re-run the pipeline to update the graph data."""
    try:
        docs_df = _parquet('documents.parquet')
        if docs_df.empty:
            return jsonify({"ok": False, "error": "No documents found"}), 404
        match = docs_df[docs_df['id'] == doc_id]
        if match.empty:
            return jsonify({"ok": False, "error": "Document not found"}), 404

        title = match.iloc[0].get('title', '') or ''
        stem  = os.path.splitext(title)[0]

        # Remove input files
        for path in [os.path.join(INPUT_FOLDER, f"{stem}.txt"),
                     os.path.join(UPLOAD_FOLDER, f"{stem}.pdf")]:
            if os.path.exists(path):
                os.remove(path)

        # Also clean Neo4j if reachable (best-effort)
        try:
            driver = get_driver()
            with driver.session() as session:
                session.execute_write(lambda tx: tx.run(
                    "MATCH (d:Document {id: $doc_id}) "
                    "OPTIONAL MATCH (d)-[:CONTAINS]->(t:TextUnit) "
                    "DETACH DELETE d, t", doc_id=doc_id
                ))
            driver.close()
        except Exception:
            pass

        return jsonify({"ok": True, "message": "Document removed. Re-run the pipeline to refresh the graph data."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route('/api/db_info')
def api_db_info():
    """Return row counts from parquet output files."""
    breakdown = []
    total = 0
    for label, fname in [
        ('Document',     'documents.parquet'),
        ('Entity',       'entities.parquet'),
        ('Relationship', 'relationships.parquet'),
        ('Community',    'community_reports.parquet'),
        ('TextUnit',     'text_units.parquet'),
        ('Claim',        'covariates.parquet'),
    ]:
        count = len(_parquet(fname))
        breakdown.append({'label': label, 'count': count})
        total += count
    return jsonify({"ok": True, "total": total, "breakdown": breakdown})


@app.route('/api/umap')
def api_umap():
    """Return entity layout coordinates from parquet or a derived graph layout."""
    ents_df  = _parquet('entities.parquet')
    rels_df  = _parquet('relationships.parquet')
    comms_df = _parquet('communities.parquet')
    tu_df    = _parquet('text_units.parquet')

    if ents_df.empty:
        return jsonify({'error': 'No pipeline output found', 'nodes': [], 'edges': []}), 404

    # ── Community membership: entity_id × level → (comm_num, ai_title) ─────────
    # Build AI title lookup from community_reports (same titles as Communities tab).
    crs_df = _parquet('community_reports.parquet')
    comm_to_ai_title = {}
    for _, row in crs_df.iterrows():
        try:
            num = int(float(row['community']))
            comm_to_ai_title[num] = row.get('title', '') or ''
        except (TypeError, ValueError):
            pass

    # level_by_entity[eid][level] = (comm_num, title)
    level_by_entity: dict = {}
    available_levels: list = []
    for _, row in comms_df.iterrows():
        try:
            level    = int(float(row['level']))
            comm_num = int(float(row['community']))
        except (TypeError, ValueError):
            continue
        if level not in available_levels:
            available_levels.append(level)
        title = comm_to_ai_title.get(comm_num, f'Community {comm_num}')
        for eid in _to_list(row.get('entity_ids')):
            level_by_entity.setdefault(eid, {})[level] = (comm_num, title)

    available_levels.sort()

    def _comm_at(eid: str, target: int):
        """Return (comm_num, title) at target level; fall back to closest coarser."""
        lvls = level_by_entity.get(eid, {})
        for l in range(target, -1, -1):
            if l in lvls:
                return lvls[l]
        return (None, '')

    # ── text_unit → document_ids mapping ─────────────────────────────────────
    tu_to_docs = {}
    for _, row in tu_df.iterrows():
        doc_ids = _to_list(row.get('document_ids'))
        if doc_ids:
            tu_to_docs[str(row['id'])] = doc_ids

    layout_pos = _build_layout_positions(ents_df, rels_df)

    # ── Nodes ─────────────────────────────────────────────────────────────────
    nodes = []
    pos   = {}
    for _, row in ents_df.iterrows():
        eid   = str(row['id'])
        name  = row.get('title', '') or ''
        if name not in layout_pos:
            continue
        x, y = layout_pos[name]
        doc_ids = []
        for tu_id in _to_list(row.get('text_unit_ids')):
            for did in tu_to_docs.get(str(tu_id), []):
                if did not in doc_ids:
                    doc_ids.append(did)
        pos[name] = (x, y)
        # Per-level community fields so the frontend can switch without re-fetching
        comm_fields: dict = {}
        for L in available_levels:
            c, t = _comm_at(eid, L)
            comm_fields[f'community_l{L}'] = c
            comm_fields[f'community_title_l{L}'] = t
        nodes.append({
            'id':              eid,
            'name':            name,
            'type':            (row.get('type', '') or '').lower(),
            'description':     (row.get('description', '') or '')[:400],
            'degree':          int(row.get('degree', 0) or 0),
            'frequency':       int(row.get('frequency', 0) or 0),
            'x': x, 'y': y,
            **comm_fields,
            'document_ids':    doc_ids,
        })

    # ── Edges ─────────────────────────────────────────────────────────────────
    edges = []
    for _, row in rels_df.iterrows():
        src, tgt = row.get('source', '') or '', row.get('target', '') or ''
        if src not in pos or tgt not in pos:
            continue
        x0, y0 = pos[src]
        x1, y1 = pos[tgt]
        edges.append({
            'source': src, 'target': tgt,
            'x0': x0, 'y0': y0, 'x1': x1, 'y1': y1,
            'weight':      float(row.get('weight', 1.0) or 1.0),
            'description': (row.get('description', '') or '')[:200],
        })

    return jsonify({'nodes': nodes, 'edges': edges, 'comm_levels': available_levels})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8501, debug=False, use_reloader=False)
