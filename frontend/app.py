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
import hashlib
import uuid

import networkx as nx
import pandas as pd
from graphrag_runtime import (
    config_uses_prompt_directory,
    find_missing_prompt_paths,
    load_settings,
    resolve_project_path,
    stage_runtime_config,
    validate_runtime_settings,
)

# ── Paths (relative to project root, where the app is launched from) ──────────
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
CONFIG_REQUEST = os.getenv('GRAPHRAG_CONFIG', 'settings.yaml')
OUTPUT_OVERRIDE = os.getenv('GRAPHRAG_OUTPUT_DIR')
CACHE_OVERRIDE = os.getenv('GRAPHRAG_CACHE_DIR')
MODE_CONFIG_REQUESTS = {
    'baseline': 'settings.yaml',
    'auto_tuned': 'settings.auto.yaml',
}
MODE_LABELS = {
    'baseline': 'Default prompts',
    'auto_tuned': 'Auto-tuned prompts',
}
MODE_ALIASES = {
    'default': 'baseline',
    'baseline': 'baseline',
    'auto': 'auto_tuned',
    'tuned': 'auto_tuned',
    'auto_tuned': 'auto_tuned',
}

PROMPT_UI_FIELDS = (
    {
        'key': 'extract_graph',
        'label': 'Extract Graph',
        'category': 'Indexing',
        'path': ('extract_graph', 'prompt'),
    },
    {
        'key': 'summarize_descriptions',
        'label': 'Summarize Descriptions',
        'category': 'Indexing',
        'path': ('summarize_descriptions', 'prompt'),
    },
    {
        'key': 'extract_claims',
        'label': 'Extract Claims',
        'category': 'Indexing',
        'path': ('extract_claims', 'prompt'),
    },
    {
        'key': 'community_report_graph',
        'label': 'Community Report Graph',
        'category': 'Indexing',
        'path': ('community_reports', 'graph_prompt'),
    },
    {
        'key': 'community_report_text',
        'label': 'Community Report Text',
        'category': 'Indexing',
        'path': ('community_reports', 'text_prompt'),
    },
    {
        'key': 'local_search',
        'label': 'Local Search',
        'category': 'Query',
        'path': ('local_search', 'prompt'),
    },
    {
        'key': 'global_search_map',
        'label': 'Global Search Map',
        'category': 'Query',
        'path': ('global_search', 'map_prompt'),
    },
    {
        'key': 'global_search_reduce',
        'label': 'Global Search Reduce',
        'category': 'Query',
        'path': ('global_search', 'reduce_prompt'),
    },
    {
        'key': 'global_search_knowledge',
        'label': 'Global Search Knowledge',
        'category': 'Query',
        'path': ('global_search', 'knowledge_prompt'),
    },
    {
        'key': 'drift_search',
        'label': 'DRIFT Search',
        'category': 'Query',
        'path': ('drift_search', 'prompt'),
    },
    {
        'key': 'drift_reduce',
        'label': 'DRIFT Reduce',
        'category': 'Query',
        'path': ('drift_search', 'reduce_prompt'),
    },
    {
        'key': 'basic_search',
        'label': 'Basic Search',
        'category': 'Query',
        'path': ('basic_search', 'prompt'),
    },
)

AUTO_TUNE_FORM_FIELDS = {
    'domain': 'DOMAIN',
    'language': 'LANGUAGE',
    'selection_method': 'SELECTION_METHOD',
    'limit': 'LIMIT',
    'max_tokens': 'MAX_TOKENS',
    'chunk_size': 'CHUNK_SIZE',
    'overlap': 'OVERLAP',
    'min_examples_required': 'MIN_EXAMPLES_REQUIRED',
    'n_subset_max': 'N_SUBSET_MAX',
    'k': 'K',
}


def _env_flag(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {'0', 'false', 'no', 'off', ''}


def _nested_value(data, *keys):
    value = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
        if value is None:
            return None
    return value


def _default_mode_from_config(config_request):
    basename = os.path.basename(str(config_request))
    return 'auto_tuned' if basename == 'settings.auto.yaml' else 'baseline'


DEFAULT_VIEW_MODE = _default_mode_from_config(CONFIG_REQUEST)


def _build_mode_state(mode):
    runtime_info = stage_runtime_config(
        MODE_CONFIG_REQUESTS[mode],
        output_override=OUTPUT_OVERRIDE if mode == DEFAULT_VIEW_MODE else None,
        cache_override=CACHE_OVERRIDE if mode == DEFAULT_VIEW_MODE else None,
    )
    uses_auto_prompts = config_uses_prompt_directory(
        runtime_info.config_path,
        'prompts_auto',
    )
    auto_tune_on_upload = uses_auto_prompts and _env_flag(
        'AUTO_TUNE_ON_UPLOAD',
        default=True,
    )
    if uses_auto_prompts:
        prompt_source_label = 'prompts_auto/ + prompts/'
        prompt_source_note = (
            'Generated indexing prompts come from prompts_auto/. '
            'Claims and query prompts still come from prompts/.'
        )
        pipeline_path = (
            'extract -> auto-tune -> index'
            if auto_tune_on_upload
            else 'extract -> index (reuse prompts_auto/)'
        )
    else:
        prompt_source_label = 'prompts/'
        prompt_source_note = 'Baseline indexing and query prompts come from prompts/.'
        pipeline_path = 'extract -> index'
    return {
        'key': mode,
        'label': MODE_LABELS[mode],
        'config_request': MODE_CONFIG_REQUESTS[mode],
        'config_path': runtime_info.config_path,
        'runtime_root': runtime_info.runtime_root,
        'output_dir': runtime_info.output_dir,
        'cache_dir': runtime_info.cache_dir,
        'reporting_dir': runtime_info.reporting_dir,
        'vector_store_dir': runtime_info.vector_store_dir,
        'uses_auto_prompts': uses_auto_prompts,
        'auto_tune_on_upload': auto_tune_on_upload,
        'pipeline_path': pipeline_path,
        'prompt_source_label': prompt_source_label,
        'prompt_source_note': prompt_source_note,
        'neo4j_sync_mode': 'manual',
    }


PIPELINE_MODES = {
    mode: _build_mode_state(mode)
    for mode in MODE_CONFIG_REQUESTS
}


def _normalize_mode(mode):
    candidate = (mode or DEFAULT_VIEW_MODE).strip().lower().replace('-', '_')
    normalized = MODE_ALIASES.get(candidate)
    if normalized not in PIPELINE_MODES:
        msg = f"Unsupported pipeline mode: {mode}"
        raise ValueError(msg)
    return normalized


def _mode_state(mode=None):
    return PIPELINE_MODES[_normalize_mode(mode)]


def _request_mode(default=None):
    requested = request.values.get('mode')
    if requested is None and request.is_json:
        payload = request.get_json(silent=True) or {}
        requested = payload.get('mode')
    try:
        return _normalize_mode(requested or default or DEFAULT_VIEW_MODE)
    except ValueError:
        return _normalize_mode(default or DEFAULT_VIEW_MODE)


UPLOAD_FOLDER = os.path.join(PROJECT_ROOT, 'frontend', 'uploads')
INPUT_FOLDER  = os.path.join(PROJECT_ROOT, 'input')
PROMPT_AUDIT_ROOT = os.path.join(PROJECT_ROOT, 'prompt_history')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(INPUT_FOLDER,  exist_ok=True)
os.makedirs(PROMPT_AUDIT_ROOT, exist_ok=True)

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
def _parquet(filename, mode=None):
    """Read a parquet from the selected output directory; return empty DataFrame if missing."""
    output_folder = _mode_state(mode)['output_dir']
    path = os.path.join(output_folder, filename)
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

def _selection_key(title, doc_id):
    title = (title or '').strip()
    return title if title else str(doc_id)


def _format_timestamp(value):
    raw = str(value or '').strip()
    if raw in {'', 'nan', 'None'}:
        return ''
    return raw.replace('T', ' ')[:19]


def _source_file_metadata(title):
    if not title:
        return {}
    source_path = os.path.join(INPUT_FOLDER, title)
    if not os.path.exists(source_path):
        return {}
    stat = os.stat(source_path)
    return {
        'source_file': title,
        'source_size_bytes': int(stat.st_size),
        'source_modified_at': time.strftime(
            '%Y-%m-%d %H:%M',
            time.localtime(stat.st_mtime),
        ),
    }


def _prompt_preview_target(prompt_path):
    active_path = prompt_path if os.path.exists(prompt_path) else None
    if active_path:
        return active_path, 'active'
    fallback_path = prompt_path.replace(
        f"{os.sep}prompts_auto{os.sep}",
        f"{os.sep}prompts{os.sep}",
    )
    if fallback_path != prompt_path and os.path.exists(fallback_path):
        return fallback_path, 'fallback'
    return None, 'missing'


def _path_timestamp_label(path):
    if not path or not os.path.exists(path):
        return None
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(os.path.getmtime(path)))


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _prompt_audit_mode_dir(mode):
    path = os.path.join(PROMPT_AUDIT_ROOT, _normalize_mode(mode))
    os.makedirs(path, exist_ok=True)
    return path


def _prompt_audit_index_path(mode):
    return os.path.join(_prompt_audit_mode_dir(mode), 'history.jsonl')


def _prompt_entries_for_mode(mode):
    config_path = _mode_state(mode)['config_path']
    settings = load_settings(config_path)
    entries = []
    for spec in PROMPT_UI_FIELDS:
        raw_path = _nested_value(settings, *spec['path'])
        if not raw_path:
            continue
        resolved_path = resolve_project_path(str(raw_path), project_root=PROJECT_ROOT)
        preview_path, source_kind = _prompt_preview_target(resolved_path)
        entries.append({
            'key': spec['key'],
            'label': spec['label'],
            'category': spec['category'],
            'path': resolved_path,
            'relative_path': os.path.relpath(resolved_path, PROJECT_ROOT),
            'exists': os.path.exists(resolved_path),
            'preview_path': preview_path,
            'preview_relative_path': (
                os.path.relpath(preview_path, PROJECT_ROOT) if preview_path else None
            ),
            'source_kind': source_kind,
            'updated_at': _path_timestamp_label(resolved_path),
            'preview_updated_at': _path_timestamp_label(preview_path),
        })
    return entries


def _record_prompt_audit(mode, document_title, uploaded_filename, auto_tune_options=None):
    mode_state = _mode_state(mode)
    doc_key = _selection_key(document_title, document_title)
    run_id = (
        time.strftime('%Y%m%dT%H%M%S', time.localtime())
        + '_'
        + _normalize_mode(mode)
        + '_'
        + uuid.uuid4().hex[:8]
    )
    run_dir = os.path.join(_prompt_audit_mode_dir(mode), run_id)
    os.makedirs(run_dir, exist_ok=True)

    prompts = []
    for entry in _prompt_entries_for_mode(mode):
        prompt_path = entry['path']
        if not os.path.exists(prompt_path):
            continue
        relative_path = entry['relative_path']
        snapshot_path = os.path.join(run_dir, relative_path)
        os.makedirs(os.path.dirname(snapshot_path), exist_ok=True)
        shutil.copy2(prompt_path, snapshot_path)
        prompts.append({
            'key': entry['key'],
            'label': entry['label'],
            'category': entry['category'],
            'path': relative_path,
            'snapshot_path': os.path.relpath(snapshot_path, PROJECT_ROOT),
            'sha256': _file_sha256(prompt_path),
            'updated_at': entry['updated_at'],
            'bytes': int(os.path.getsize(prompt_path)),
        })

    manifest = {
        'run_id': run_id,
        'mode': mode_state['key'],
        'mode_label': mode_state['label'],
        'recorded_at': time.strftime('%Y-%m-%d %H:%M', time.localtime()),
        'document_title': document_title,
        'document_key': doc_key,
        'uploaded_filename': uploaded_filename,
        'config_path': os.path.relpath(mode_state['config_path'], PROJECT_ROOT),
        'output_dir': os.path.relpath(mode_state['output_dir'], PROJECT_ROOT),
        'prompt_source_note': mode_state['prompt_source_note'],
        'pipeline_path': mode_state['pipeline_path'],
        'auto_tune_on_upload': bool(mode_state['auto_tune_on_upload']),
        'auto_tune_options': dict(auto_tune_options or {}),
        'prompts': prompts,
    }
    manifest_path = os.path.join(run_dir, 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as handle:
        _json.dump(manifest, handle, indent=2)

    summary = {
        'run_id': run_id,
        'mode': mode_state['key'],
        'mode_label': mode_state['label'],
        'recorded_at': manifest['recorded_at'],
        'document_title': document_title,
        'document_key': doc_key,
        'uploaded_filename': uploaded_filename,
        'config_path': manifest['config_path'],
        'output_dir': manifest['output_dir'],
        'pipeline_path': manifest['pipeline_path'],
        'prompt_count': len(prompts),
        'manifest_path': os.path.relpath(manifest_path, PROJECT_ROOT),
        'auto_tune_on_upload': manifest['auto_tune_on_upload'],
        'auto_tune_options': manifest['auto_tune_options'],
        'extract_graph_path': next(
            (prompt['snapshot_path'] for prompt in prompts if prompt['key'] == 'extract_graph'),
            None,
        ),
        'extract_graph_sha256': next(
            (prompt['sha256'] for prompt in prompts if prompt['key'] == 'extract_graph'),
            None,
        ),
    }
    with open(_prompt_audit_index_path(mode), 'a', encoding='utf-8') as handle:
        handle.write(_json.dumps(summary) + '\n')
    return summary


def _load_prompt_audit_index(mode):
    path = _prompt_audit_index_path(mode)
    records = {}
    if not os.path.exists(path):
        return records
    with open(path, 'r', encoding='utf-8') as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = _json.loads(line)
            except ValueError:
                continue
            key = record.get('document_key') or record.get('document_title')
            if key:
                records[key] = record
    return records


def _load_prompt_audit_manifest(mode, run_id):
    if not run_id:
        return None
    path = os.path.join(_prompt_audit_mode_dir(mode), run_id, 'manifest.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as handle:
        return _json.load(handle)


def _parse_auto_tune_options(form_data):
    options = {}
    for form_name, env_name in AUTO_TUNE_FORM_FIELDS.items():
        value = str(form_data.get(form_name, '') or '').strip()
        if value:
            options[env_name] = value
    discover_entity_types = form_data.get('discover_entity_types')
    if discover_entity_types is not None:
        options['DISCOVER_ENTITY_TYPES'] = (
            'true' if str(discover_entity_types).lower() in {'1', 'true', 'on', 'yes'} else 'false'
        )
    return options


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
    "mode":   DEFAULT_VIEW_MODE,
    "mode_label": MODE_LABELS[DEFAULT_VIEW_MODE],
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


def _validate_mode_config(mode, *, allow_missing_tuned_prompts=False):
    graphrag_config = _mode_state(mode)['config_path']
    if allow_missing_tuned_prompts and find_missing_prompt_paths(graphrag_config):
        return
    validate_runtime_settings(graphrag_config)


def run_full_pipeline(pdf_path, stem, mode, auto_tune_options=None):
    """Background thread: extract → prompt tune (optional) → graphrag index."""
    mode_state = _mode_state(mode)
    graphrag_config = mode_state['config_path']
    runtime_root = mode_state['runtime_root']
    output_folder = mode_state['output_dir']
    vector_store_dir = mode_state['vector_store_dir']
    auto_tune_on_upload = mode_state['auto_tune_on_upload']
    mode_label = mode_state['label']

    with pipeline_lock:
        pipeline_state["status"] = "running"
        pipeline_state["stage"]  = ""
        pipeline_state["log"]    = []
        pipeline_state["error"]  = None
        pipeline_state["mode"]   = mode
        pipeline_state["mode_label"] = mode_label

    try:
        _log(f"Selected upload mode → {mode_label}")
        _log(f"Using GraphRAG config → {os.path.relpath(graphrag_config, PROJECT_ROOT)}")
        _log(f"Using GraphRAG runtime root → {os.path.relpath(runtime_root, PROJECT_ROOT)}")
        _log(f"Using GraphRAG output → {os.path.relpath(output_folder, PROJECT_ROOT)}")
        _log(
            "Automatic prompt tuning on upload → "
            + ("enabled" if auto_tune_on_upload else "disabled")
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

        # 2 ─ Auto prompt tuning for the tuned config ─────────────────────────
        if auto_tune_on_upload:
            _set_stage("Auto-tuning prompts from the current input corpus")
            auto_tune_env = dict(os.environ)
            auto_tune_env['GRAPHRAG_CONFIG'] = graphrag_config
            for env_name, value in (auto_tune_options or {}).items():
                auto_tune_env[env_name] = value
                _log(f"Auto-tune option → {env_name}={value}")
            ok = _run_step(
                [os.path.join(PROJECT_ROOT, 'auto_tune.sh')],
                env=auto_tune_env,
            )
            if not ok:
                raise RuntimeError("auto_tune.sh failed – check the log above.")
        else:
            _validate_mode_config(mode)

        _validate_mode_config(mode)

        # 3 ─ Reset the vector store output ───────────────────────────────────
        _set_stage("Resetting vector store")
        if os.path.isdir(vector_store_dir):
            shutil.rmtree(vector_store_dir)
            _log(
                "Removed existing vector store → "
                + os.path.relpath(vector_store_dir, PROJECT_ROOT)
            )
        else:
            _log(
                "Vector store will be created → "
                + os.path.relpath(vector_store_dir, PROJECT_ROOT)
            )

        # 4 ─ GraphRAG Incremental ─────────────────────────────────────────────
        _set_stage("Keeping cache for incremental indexing")
        _log("Cache retained.")

        # 5 ─ Run graphrag index ───────────────────────────────────────────────
        _set_stage("Running GraphRAG indexing (this may take several minutes…)")
        index_cmd = GRAPHRAG_CMD + ['index', '--root', runtime_root]
        ok = _run_step(index_cmd)
        if not ok:
            raise RuntimeError("graphrag index failed – check the log above.")

        try:
            prompt_audit = _record_prompt_audit(
                mode,
                f"{stem}.txt",
                os.path.basename(pdf_path),
                auto_tune_options=auto_tune_options,
            )
            _log(
                "Prompt snapshot recorded → "
                + prompt_audit["manifest_path"]
            )
        except Exception as audit_exc:
            _log(f"⚠ Prompt snapshot could not be recorded: {audit_exc}")

        with pipeline_lock:
            pipeline_state["status"] = "done"
            pipeline_state["stage"]  = "Indexed"
        _log("✅ GraphRAG indexing finished.")
        _log("Use Documents → Sync Neo4j to populate Neo4j manually.")

    except Exception as exc:
        with pipeline_lock:
            pipeline_state["status"] = "error"
            pipeline_state["stage"]  = "Error"
            pipeline_state["error"]  = str(exc)
        _log(f"❌ Pipeline error: {exc}")


def run_neo4j_sync(mode):
    """Background thread: import the selected GraphRAG output into Neo4j."""
    mode_state = _mode_state(mode)
    output_folder = mode_state['output_dir']
    mode_label = mode_state['label']

    with pipeline_lock:
        pipeline_state["status"] = "running"
        pipeline_state["stage"] = "Syncing Neo4j"
        pipeline_state["log"] = []
        pipeline_state["error"] = None
        pipeline_state["mode"] = mode
        pipeline_state["mode_label"] = mode_label

    try:
        documents_path = os.path.join(output_folder, 'documents.parquet')
        if not os.path.exists(documents_path):
            raise RuntimeError(
                "No indexed GraphRAG output exists for this mode yet. Run indexing first."
            )

        _log(f"Selected Neo4j sync mode → {mode_label}")
        _log(f"Using GraphRAG output → {os.path.relpath(output_folder, PROJECT_ROOT)}")
        ok = _run_step(
            [PYTHON_BIN, os.path.join(PROJECT_ROOT, 'import_neo4j.py')],
            env={**os.environ, 'OUTPUT_DIR': output_folder},
        )
        if not ok:
            raise RuntimeError("import_neo4j.py failed – check the log above.")

        with pipeline_lock:
            pipeline_state["status"] = "done"
            pipeline_state["stage"] = "Neo4j synced"
        _log("✅ Neo4j population finished.")
    except Exception as exc:
        with pipeline_lock:
            pipeline_state["status"] = "error"
            pipeline_state["stage"] = "Error"
            pipeline_state["error"] = str(exc)
        _log(f"❌ Neo4j sync error: {exc}")

# ── Flask app ─────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

@app.route('/')
def index():
    return render_template(
        'index.html',
        default_view_mode=DEFAULT_VIEW_MODE,
        available_modes=[PIPELINE_MODES[key] for key in MODE_CONFIG_REQUESTS],
        mode_labels=MODE_LABELS,
    )

@app.route('/upload', methods=['POST'])
def upload():
    mode = _request_mode()
    mode_state = _mode_state(mode)

    if pipeline_state["status"] == "running":
        return jsonify({"error": "A pipeline is already running. Please wait."}), 409
    try:
        _validate_mode_config(
            mode,
            allow_missing_tuned_prompts=mode_state['auto_tune_on_upload'],
        )
    except (FileNotFoundError, ValueError) as exc:
        return jsonify({
            "error": str(exc),
            "missing_prompts": find_missing_prompt_paths(mode_state['config_path']),
            "mode": mode,
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
    auto_tune_options = _parse_auto_tune_options(request.form)

    t = threading.Thread(
        target=run_full_pipeline,
        args=(save_path, stem, mode, auto_tune_options),
        daemon=True,
    )
    t.start()
    return jsonify({"ok": True, "filename": filename, "mode": mode})

@app.route('/api/status')
def api_status():
    with pipeline_lock:
        return jsonify({
            "status": pipeline_state["status"],
            "stage":  pipeline_state["stage"],
            "log":    pipeline_state["log"][-100:],   # last 100 lines
            "error":  pipeline_state["error"],
            "mode":   pipeline_state["mode"],
            "mode_label": pipeline_state["mode_label"],
        })

@app.route('/api/data')
def api_data():
    """Return all graph data read directly from parquet pipeline output."""
    mode = _request_mode()
    docs_df  = _parquet('documents.parquet', mode)
    ents_df  = _parquet('entities.parquet', mode)
    rels_df  = _parquet('relationships.parquet', mode)
    comms_df = _parquet('communities.parquet', mode)
    crs_df   = _parquet('community_reports.parquet', mode)
    tu_df    = _parquet('text_units.parquet', mode)
    cov_df   = _parquet('covariates.parquet', mode)

    if docs_df.empty and ents_df.empty:
        return jsonify({'documents': [], 'entities': [], 'claims': [],
                        'communities': [], 'relationships': [], 'stats': [],
                        'mode': mode, 'mode_label': _mode_state(mode)['label']})

    prompt_audit_by_key = _load_prompt_audit_index(mode)
    doc_meta_by_id = {}
    for _, row in docs_df.iterrows():
        doc_id = str(row['id'])
        title = row.get('title', '') or ''
        selection_key = _selection_key(title, doc_id)
        prompt_audit = (
            prompt_audit_by_key.get(selection_key)
            or prompt_audit_by_key.get(title)
        )
        doc_meta_by_id[doc_id] = {
            'id': doc_id,
            'title': title,
            'selection_key': selection_key,
            'creation_date': _format_timestamp(row.get('creation_date')),
            'text_units': 0,
            'entity_count': 0,
            'claim_count': 0,
            'characters': len(row.get('text', '') or ''),
            'prompt_audit_run_id': prompt_audit.get('run_id') if prompt_audit else '',
            'prompt_audit_recorded_at': prompt_audit.get('recorded_at') if prompt_audit else '',
            'prompt_audit_manifest_path': prompt_audit.get('manifest_path') if prompt_audit else '',
            'prompt_audit_prompt_count': prompt_audit.get('prompt_count') if prompt_audit else 0,
            'prompt_audit_extract_graph_path': prompt_audit.get('extract_graph_path') if prompt_audit else '',
            'prompt_audit_extract_graph_sha256': prompt_audit.get('extract_graph_sha256') if prompt_audit else '',
            'prompt_audit_mode_label': prompt_audit.get('mode_label') if prompt_audit else '',
            'prompt_audit_pipeline_path': prompt_audit.get('pipeline_path') if prompt_audit else '',
            'prompt_audit_auto_tune_on_upload': (
                bool(prompt_audit.get('auto_tune_on_upload'))
                if prompt_audit else False
            ),
            'prompt_audit_auto_tune_options': (
                prompt_audit.get('auto_tune_options') if prompt_audit else {}
            ),
            **_source_file_metadata(title),
        }

    # ── text_unit_id → [document_ids] lookup ─────────────────────────────────
    tu_to_docs = {}
    for _, row in tu_df.iterrows():
        doc_ids = _to_list(row.get('document_ids'))
        if doc_ids:
            tu_to_docs[str(row['id'])] = doc_ids
            for did in doc_ids:
                meta = doc_meta_by_id.get(str(did))
                if meta:
                    meta['text_units'] += 1
    tu_to_first_doc = {k: v[0] for k, v in tu_to_docs.items()}
    doc_id_to_key = {
        doc_id: meta['selection_key']
        for doc_id, meta in doc_meta_by_id.items()
    }

    # ── Entities ─────────────────────────────────────────────────────────────
    entities = []
    for _, row in ents_df.iterrows():
        doc_ids = []
        for tu_id in _to_list(row.get('text_unit_ids')):
            for did in tu_to_docs.get(str(tu_id), []):
                if did not in doc_ids:
                    doc_ids.append(did)
        for did in doc_ids:
            meta = doc_meta_by_id.get(str(did))
            if meta:
                meta['entity_count'] += 1
        entities.append({
            'id':          str(row['id']),
            'name':        row.get('title', '') or '',
            'type':        (row.get('type', '') or '').lower(),
            'description': row.get('description', '') or '',
            'degree':      int(row.get('degree', 0) or 0),
            'frequency':   int(row.get('frequency', 0) or 0),
            'document_ids': doc_ids,
            'document_keys': [
                doc_id_to_key[str(did)]
                for did in doc_ids
                if str(did) in doc_id_to_key
            ],
        })
    entities.sort(key=lambda x: x['degree'], reverse=True)
    entities = entities[:300]

    # ── Claims / Covariates ───────────────────────────────────────────────────
    claims = []
    for _, row in cov_df.iterrows():
        tu_id = str(row.get('text_unit_id', '') or '')
        raw_start = str(row.get('start_date', '') or '')
        raw_end   = str(row.get('end_date',   '') or '')
        document_id = tu_to_first_doc.get(tu_id)
        if document_id is not None:
            meta = doc_meta_by_id.get(str(document_id))
            if meta:
                meta['claim_count'] += 1
        claims.append({
            'id':          str(row['id']),
            'type':        _clean_type(row.get('type', '') or ''),
            'description': row.get('description', '') or '',
            'status':      row.get('status', '') or '',
            'subject':     row.get('subject_id', '') or '',
            'object':      row.get('object_id', '') or '',
            'start_date':  raw_start[:10] if raw_start not in ('', 'nan', 'None') else '',
            'end_date':    raw_end[:10]   if raw_end   not in ('', 'nan', 'None') else '',
            'document_id': document_id,
            'document_key': doc_id_to_key.get(str(document_id), ''),
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
    documents = sorted(doc_meta_by_id.values(), key=lambda doc: doc['title'].lower())

    return jsonify({
        'documents':     documents,
        'entities':      entities,
        'claims':        claims,
        'communities':   communities,
        'relationships': relationships,
        'stats':         stats,
        'mode':          mode,
        'mode_label':    _mode_state(mode)['label'],
    })


@app.route('/api/prompts')
def api_prompts():
    mode = _request_mode()
    entries = _prompt_entries_for_mode(mode)
    if not entries:
        return jsonify({
            'mode': mode,
            'mode_label': _mode_state(mode)['label'],
            'entries': [],
            'selected': None,
        })

    requested_key = (request.args.get('key') or '').strip()
    selected = next((entry for entry in entries if entry['key'] == requested_key), entries[0])
    content = ''
    if selected['preview_path'] and os.path.exists(selected['preview_path']):
        with open(selected['preview_path'], 'r', encoding='utf-8') as handle:
            content = handle.read()

    return jsonify({
        'mode': mode,
        'mode_label': _mode_state(mode)['label'],
        'entries': [
            {
                'key': entry['key'],
                'label': entry['label'],
                'category': entry['category'],
                'path': entry['relative_path'],
                'exists': entry['exists'],
                'preview_path': entry['preview_relative_path'],
                'source_kind': entry['source_kind'],
                'updated_at': entry['updated_at'],
                'preview_updated_at': entry['preview_updated_at'],
            }
            for entry in entries
        ],
        'selected': {
            'key': selected['key'],
            'label': selected['label'],
            'category': selected['category'],
            'path': selected['relative_path'],
            'exists': selected['exists'],
            'preview_path': selected['preview_relative_path'],
            'source_kind': selected['source_kind'],
            'updated_at': selected['updated_at'],
            'preview_updated_at': selected['preview_updated_at'],
            'content': content,
        },
    })


@app.route('/api/document-prompts')
def api_document_prompts():
    mode = _request_mode()
    document_key = (request.args.get('document_key') or '').strip()
    requested_key = (request.args.get('key') or '').strip()
    if not document_key:
        return jsonify({'error': 'Missing document_key.', 'mode': mode}), 400

    history = _load_prompt_audit_index(mode)
    record = history.get(document_key)
    if not record:
        return jsonify({
            'error': 'No prompt provenance has been recorded for this document yet.',
            'mode': mode,
            'mode_label': _mode_state(mode)['label'],
            'document_key': document_key,
        }), 404

    manifest = _load_prompt_audit_manifest(mode, record.get('run_id'))
    if not manifest:
        return jsonify({
            'error': 'The prompt provenance manifest for this document is missing.',
            'mode': mode,
            'mode_label': _mode_state(mode)['label'],
            'document_key': document_key,
            'record': record,
        }), 404

    entries = manifest.get('prompts', [])
    selected = next((entry for entry in entries if entry.get('key') == requested_key), None)
    if selected is None and entries:
        selected = entries[0]

    content = ''
    if selected and selected.get('snapshot_path'):
        selected_path = resolve_project_path(selected['snapshot_path'], project_root=PROJECT_ROOT)
        if os.path.exists(selected_path):
            with open(selected_path, 'r', encoding='utf-8') as handle:
                content = handle.read()

    return jsonify({
        'mode': mode,
        'mode_label': _mode_state(mode)['label'],
        'record': record,
        'entries': entries,
        'selected': (
            {
                **selected,
                'content': content,
            }
            if selected else None
        ),
    })


@app.route('/api/neo4j/sync', methods=['POST'])
def api_neo4j_sync():
    mode = _request_mode()
    mode_state = _mode_state(mode)
    if pipeline_state["status"] == "running":
        return jsonify({"error": "Another task is already running. Please wait."}), 409

    documents_path = os.path.join(mode_state['output_dir'], 'documents.parquet')
    if not os.path.exists(documents_path):
        return jsonify({
            "error": "No indexed GraphRAG output exists for this mode yet. Run indexing first.",
            "mode": mode,
        }), 400

    t = threading.Thread(target=run_neo4j_sync, args=(mode,), daemon=True)
    t.start()
    return jsonify({"ok": True, "mode": mode})

@app.route('/api/clear', methods=['POST'])
def api_clear():
    """Wipe pipeline output, input files, and cache. Also clears Neo4j if reachable."""
    mode = _request_mode()
    mode_state = _mode_state(mode)
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
    if os.path.exists(mode_state['output_dir']):
        shutil.rmtree(mode_state['output_dir'])

    # 4. Clear GraphRAG cache
    if os.path.exists(mode_state['cache_dir']):
        shutil.rmtree(mode_state['cache_dir'])

    msg = "Cleared." + (f" (warnings: {'; '.join(errors)})" if errors else "")
    return jsonify({"ok": True, "message": msg})


@app.route('/api/db_info')
def api_db_info():
    """Return row counts from parquet output files."""
    mode = _request_mode()
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
        count = len(_parquet(fname, mode))
        breakdown.append({'label': label, 'count': count})
        total += count
    return jsonify({
        "ok": True,
        "total": total,
        "breakdown": breakdown,
        "mode": mode,
        "mode_label": _mode_state(mode)['label'],
    })


@app.route('/api/umap')
def api_umap():
    """Return entity layout coordinates from parquet or a derived graph layout."""
    mode = _request_mode()
    docs_df  = _parquet('documents.parquet', mode)
    ents_df  = _parquet('entities.parquet', mode)
    rels_df  = _parquet('relationships.parquet', mode)
    comms_df = _parquet('communities.parquet', mode)
    tu_df    = _parquet('text_units.parquet', mode)

    if ents_df.empty:
        return jsonify({'error': 'No pipeline output found', 'nodes': [], 'edges': []}), 404

    # ── Community membership: entity_id × level → (comm_num, ai_title) ─────────
    # Build AI title lookup from community_reports (same titles as Communities tab).
    crs_df = _parquet('community_reports.parquet', mode)
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

    doc_id_to_key = {
        str(row['id']): _selection_key(row.get('title', '') or '', str(row['id']))
        for _, row in docs_df.iterrows()
    }

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
            'document_keys':   [
                doc_id_to_key[str(did)]
                for did in doc_ids
                if str(did) in doc_id_to_key
            ],
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

    return jsonify({
        'nodes': nodes,
        'edges': edges,
        'comm_levels': available_levels,
        'mode': mode,
        'mode_label': _mode_state(mode)['label'],
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8501, debug=False, use_reloader=False)
