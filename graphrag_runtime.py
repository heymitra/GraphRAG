#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import argparse
import copy
import dataclasses as std_dataclasses
import json
import shlex
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parent

PROMPT_PATH_KEYS = (
    ("extract_graph", "prompt"),
    ("summarize_descriptions", "prompt"),
    ("extract_claims", "prompt"),
    ("community_reports", "graph_prompt"),
    ("community_reports", "text_prompt"),
    ("local_search", "prompt"),
    ("global_search", "map_prompt"),
    ("global_search", "reduce_prompt"),
    ("global_search", "knowledge_prompt"),
    ("drift_search", "prompt"),
    ("drift_search", "reduce_prompt"),
    ("basic_search", "prompt"),
)

LEGACY_PROMPT_PLACEHOLDERS = (
    "{tuple_delimiter}",
    "{record_delimiter}",
    "{completion_delimiter}",
)

KNOWN_EMBEDDING_VECTOR_SIZES = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
}


@dataclass
class RuntimeConfigInfo:
    config_path: str
    runtime_root: str
    input_dir: str
    output_dir: str
    cache_dir: str
    reporting_dir: str
    vector_store_dir: str


@dataclass
class PromptTuneLimitInfo:
    root: str
    available_chunks: int
    requested_limit: int
    effective_limit: int
    chunk_size: int | None
    overlap: int | None


def _format_missing_prompt_message(
    config_path: Path,
    missing_prompts: list[str],
) -> str:
    lines = [
        f"Missing prompt files for config: {config_path}",
        *[f" - {path}" for path in missing_prompts],
    ]
    if "settings.auto" in config_path.name:
        lines.extend(
            [
                "",
                "This tuned config expects prompt tuning output in prompts_auto/.",
                'Run: DOMAIN="your corpus domain" ./auto_tune.sh',
                "Then rerun the tuned indexing command.",
            ]
        )
    return "\n".join(lines)


def _format_legacy_prompt_message(
    config_path: Path,
    legacy_prompts: dict[str, list[str]],
) -> str:
    lines = [
        f"Incompatible GraphRAG 3.x prompt syntax for config: {config_path}",
        "The following prompt files still use legacy 2.x delimiter placeholders:",
    ]
    for path, placeholders in legacy_prompts.items():
        lines.append(f" - {path} -> {', '.join(placeholders)}")
    lines.extend(
        [
            "",
            "GraphRAG 3.x expects literal delimiters inside the prompt text:",
            " - tuple delimiter: <|>",
            " - record delimiter: ##",
            " - completion delimiter: <|COMPLETE|>",
            "",
            "Replace the legacy placeholders or regenerate the prompts with GraphRAG 3.x.",
        ]
    )
    return "\n".join(lines)


def _format_vector_size_message(
    config_path: Path,
    issues: list[str],
) -> str:
    lines = [
        f"Embedding/vector-store mismatch for config: {config_path}",
        *[f" - {issue}" for issue in issues],
        "",
        "The vector store dimension must match the embedding model output size.",
        "Examples:",
        " - text-embedding-3-small -> 1536",
        " - text-embedding-3-large -> 3072",
        "",
        "Update vector_store.vector_size in the config before rerunning indexing.",
    ]
    return "\n".join(lines)


def resolve_config_path(config_path: str, project_root: Path = PROJECT_ROOT) -> Path:
    path = Path(config_path)
    if not path.is_absolute():
        path = project_root / path
    return path.resolve()


def load_settings(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        msg = f"Config file must contain a YAML mapping: {path}"
        raise ValueError(msg)
    return data


def _get_nested(data: dict[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
        if value is None:
            return None
    return value


def _set_nested(data: dict[str, Any], *keys: str, value: Any) -> None:
    cursor = data
    for key in keys[:-1]:
        next_value = cursor.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            cursor[key] = next_value
        cursor = next_value
    cursor[keys[-1]] = value


def _get_embedding_model_name(settings: dict[str, Any]) -> str | None:
    model_id = _get_nested(settings, "embed_text", "embedding_model_id")
    if not model_id:
        return None
    model_config = _get_nested(settings, "embedding_models", str(model_id))
    if not isinstance(model_config, dict):
        return None
    model_name = model_config.get("model")
    return str(model_name) if model_name else None


def find_vector_size_issues(
    config_path: str | Path,
) -> list[str]:
    settings = load_settings(config_path)
    model_name = _get_embedding_model_name(settings)
    if not model_name:
        return []

    expected_size = KNOWN_EMBEDDING_VECTOR_SIZES.get(model_name)
    if expected_size is None:
        return []

    issues: list[str] = []
    configured_default = _get_nested(settings, "vector_store", "vector_size")
    if configured_default is None:
        if expected_size != 3072:
            issues.append(
                "vector_store.vector_size is not set, so GraphRAG will default to 3072 "
                f"even though {model_name} returns {expected_size}-dimensional vectors."
            )
    else:
        try:
            default_size = int(configured_default)
        except (TypeError, ValueError):
            issues.append(
                f"vector_store.vector_size must be an integer, got {configured_default!r}."
            )
        else:
            if default_size != expected_size:
                issues.append(
                    f"vector_store.vector_size={default_size}, but {model_name} returns "
                    f"{expected_size}-dimensional vectors."
                )

    index_schema = _get_nested(settings, "vector_store", "index_schema")
    if isinstance(index_schema, dict):
        for index_name, schema in index_schema.items():
            if not isinstance(schema, dict):
                continue
            vector_size = schema.get("vector_size")
            if vector_size is None:
                continue
            try:
                parsed_size = int(vector_size)
            except (TypeError, ValueError):
                issues.append(
                    f"vector_store.index_schema.{index_name}.vector_size must be an integer, "
                    f"got {vector_size!r}."
                )
                continue
            if parsed_size != expected_size:
                issues.append(
                    f"vector_store.index_schema.{index_name}.vector_size={parsed_size}, but "
                    f"{model_name} returns {expected_size}-dimensional vectors."
                )

    return issues


def resolve_project_path(
    path_value: str | None,
    *,
    project_root: Path = PROJECT_ROOT,
    fallback: str | None = None,
) -> str:
    value = path_value or fallback
    if value is None:
        msg = "A path value or fallback is required."
        raise ValueError(msg)
    path = Path(value)
    if not path.is_absolute():
        path = project_root / path
    return str(path.resolve())


def get_input_dir(
    settings: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> str:
    return resolve_project_path(
        _get_nested(settings, "input_storage", "base_dir")
        or _get_nested(settings, "input", "storage", "base_dir"),
        project_root=project_root,
        fallback="input",
    )


def get_output_dir(
    settings: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
    output_override: str | None = None,
) -> str:
    return resolve_project_path(
        output_override
        or _get_nested(settings, "output_storage", "base_dir")
        or _get_nested(settings, "output", "base_dir"),
        project_root=project_root,
        fallback="output",
    )


def get_cache_dir(
    settings: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
    cache_override: str | None = None,
) -> str:
    return resolve_project_path(
        cache_override
        or _get_nested(settings, "cache", "storage", "base_dir")
        or _get_nested(settings, "cache", "base_dir"),
        project_root=project_root,
        fallback="cache",
    )


def get_reporting_dir(
    settings: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
    reporting_override: str | None = None,
) -> str:
    return resolve_project_path(
        reporting_override or _get_nested(settings, "reporting", "base_dir"),
        project_root=project_root,
        fallback="logs",
    )


def _get_vector_store_uri(
    settings: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
    output_dir: str,
    output_override: str | None = None,
) -> str:
    current = _get_nested(settings, "vector_store", "db_uri") or _get_nested(
        settings, "vector_store", "default_vector_store", "db_uri"
    )
    if output_override:
        return str((Path(output_dir) / "lancedb").resolve())
    return resolve_project_path(
        current,
        project_root=project_root,
        fallback=str(Path(output_dir) / "lancedb"),
    )


def _absolutize_prompt_paths(
    settings: dict[str, Any],
    *,
    project_root: Path = PROJECT_ROOT,
) -> None:
    for key_path in PROMPT_PATH_KEYS:
        current = _get_nested(settings, *key_path)
        if current:
            _set_nested(
                settings,
                *key_path,
                value=resolve_project_path(
                    str(current),
                    project_root=project_root,
                ),
            )


def _rewrite_prompt_directory(
    path_value: str,
    *,
    source_dir: str,
    target_dir: str,
) -> str:
    path = Path(str(path_value))
    parts = list(path.parts)
    try:
        index = parts.index(source_dir)
    except ValueError:
        return str(path_value)
    parts[index] = target_dir
    return str(Path(*parts))


def _fallback_prompt_directory(
    settings: dict[str, Any],
    *,
    source_dir: str,
    target_dir: str,
    project_root: Path = PROJECT_ROOT,
) -> None:
    for key_path in PROMPT_PATH_KEYS:
        current = _get_nested(settings, *key_path)
        if not current:
            continue
        fallback = _rewrite_prompt_directory(
            str(current),
            source_dir=source_dir,
            target_dir=target_dir,
        )
        if fallback == str(current):
            continue
        fallback_path = Path(
            resolve_project_path(
                fallback,
                project_root=project_root,
            )
        )
        if fallback_path.exists():
            _set_nested(settings, *key_path, value=fallback)


def get_prompt_paths(
    config_path: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> list[str]:
    resolved_config = resolve_config_path(str(config_path), project_root=project_root)
    settings = copy.deepcopy(load_settings(resolved_config))
    _absolutize_prompt_paths(settings, project_root=project_root)

    prompt_paths: list[str] = []
    for key_path in PROMPT_PATH_KEYS:
        current = _get_nested(settings, *key_path)
        if current:
            prompt_paths.append(str(current))
    return prompt_paths


def config_uses_prompt_directory(
    config_path: str | Path,
    prompt_dir_name: str,
    *,
    project_root: Path = PROJECT_ROOT,
) -> bool:
    prompt_dir_fragment = f"/{prompt_dir_name.strip('/')}/"
    return any(
        prompt_dir_fragment in Path(path).as_posix()
        for path in get_prompt_paths(config_path, project_root=project_root)
    )


def find_missing_prompt_paths(
    config_path: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> list[str]:
    return [
        path
        for path in get_prompt_paths(config_path, project_root=project_root)
        if not Path(path).exists()
    ]


def find_legacy_prompt_placeholders(
    config_path: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, list[str]]:
    legacy_prompts: dict[str, list[str]] = {}
    for path in get_prompt_paths(config_path, project_root=project_root):
        prompt_path = Path(path)
        if not prompt_path.exists():
            continue
        prompt_text = prompt_path.read_text(encoding="utf-8")
        matches = [
            placeholder
            for placeholder in LEGACY_PROMPT_PLACEHOLDERS
            if placeholder in prompt_text
        ]
        if matches:
            legacy_prompts[str(prompt_path)] = matches
    return legacy_prompts


def validate_prompt_paths(
    config_path: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> None:
    resolved_config = resolve_config_path(str(config_path), project_root=project_root)
    missing_prompts = find_missing_prompt_paths(
        resolved_config,
        project_root=project_root,
    )
    if missing_prompts:
        raise FileNotFoundError(
            _format_missing_prompt_message(resolved_config, missing_prompts)
        )
    legacy_prompts = find_legacy_prompt_placeholders(
        resolved_config,
        project_root=project_root,
    )
    if legacy_prompts:
        raise ValueError(
            _format_legacy_prompt_message(resolved_config, legacy_prompts)
        )


def validate_runtime_settings(
    config_path: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> None:
    resolved_config = resolve_config_path(str(config_path), project_root=project_root)
    validate_prompt_paths(resolved_config, project_root=project_root)
    vector_size_issues = find_vector_size_issues(resolved_config)
    if vector_size_issues:
        raise ValueError(
            _format_vector_size_message(resolved_config, vector_size_issues)
        )


def ensure_prompt_paths_exist(
    config_path: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
) -> None:
    validate_prompt_paths(config_path, project_root=project_root)


def _runtime_root_for(
    config_path: Path,
    *,
    project_root: Path = PROJECT_ROOT,
    suffix: str | None = None,
) -> Path:
    try:
        rel = config_path.relative_to(project_root)
        safe_name = "__".join(rel.parts)
    except ValueError:
        safe_name = config_path.name
    safe_name = safe_name.replace(".", "_")
    if suffix:
        safe_name = f"{safe_name}__{suffix}"
    return (project_root / ".graphrag-runtime" / safe_name).resolve()


def stage_runtime_config(
    config_path: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
    output_override: str | None = None,
    cache_override: str | None = None,
    reporting_override: str | None = None,
    for_prompt_tune: bool = False,
    file_pattern: str | None = None,
    runtime_suffix: str | None = None,
) -> RuntimeConfigInfo:
    """Stage a GraphRAG config into a runtime root with absolute paths.

    Args:
        config_path: Path to the GraphRAG settings YAML to stage.
        project_root: Repository root (used to resolve relative paths).
        output_override: Override the configured output directory.
        cache_override: Override the configured cache directory.
        reporting_override: Override the configured reporting directory.
        for_prompt_tune: Stage a prompt-tune-safe config (rewrites prompts_auto → prompts).
        file_pattern: Optional regex to inject as ``input.file_pattern``.
            When set, GraphRAG will only index files whose names match this pattern,
            allowing single-file indexing without touching other files in input/.
        runtime_suffix: Optional extra suffix for the ``.graphrag-runtime/`` subdirectory.
            Use this to create a unique runtime root for a per-upload run so it does not
            overwrite the default pre-staged config used for dataset browsing.
    """
    resolved_config = resolve_config_path(str(config_path), project_root=project_root)
    settings = load_settings(resolved_config)
    staged = copy.deepcopy(settings)

    input_dir = get_input_dir(staged, project_root=project_root)
    output_dir = get_output_dir(
        staged,
        project_root=project_root,
        output_override=output_override,
    )
    cache_dir = get_cache_dir(
        staged,
        project_root=project_root,
        cache_override=cache_override,
    )
    reporting_dir = get_reporting_dir(
        staged,
        project_root=project_root,
        reporting_override=reporting_override,
    )
    vector_store_uri = _get_vector_store_uri(
        staged,
        project_root=project_root,
        output_dir=output_dir,
        output_override=output_override,
    )

    if "input_storage" in staged or _get_nested(staged, "input", "storage", "base_dir"):
        _set_nested(staged, "input_storage", "base_dir", value=input_dir)
    if "output_storage" in staged or "output" in staged:
        _set_nested(staged, "output_storage", "base_dir", value=output_dir)
    if "cache" in staged:
        _set_nested(staged, "cache", "storage", "base_dir", value=cache_dir)
    if "reporting" in staged:
        _set_nested(staged, "reporting", "base_dir", value=reporting_dir)
    if "vector_store" in staged:
        _set_nested(staged, "vector_store", "db_uri", value=vector_store_uri)

    # Restrict which files GraphRAG indexes (single-file upload support).
    if file_pattern is not None:
        _set_nested(staged, "input", "file_pattern", value=file_pattern)

    if for_prompt_tune:
        _fallback_prompt_directory(
            staged,
            source_dir="prompts_auto",
            target_dir="prompts",
            project_root=project_root,
        )
    _absolutize_prompt_paths(staged, project_root=project_root)

    # Determine the suffix for the runtime root directory.
    if for_prompt_tune:
        root_suffix = "prompt_tune"
    elif runtime_suffix:
        root_suffix = runtime_suffix
    else:
        root_suffix = None

    runtime_root = _runtime_root_for(
        resolved_config,
        project_root=project_root,
        suffix=root_suffix,
    )
    runtime_root.mkdir(parents=True, exist_ok=True)

    runtime_settings_path = runtime_root / "settings.yaml"
    runtime_settings_path.write_text(
        yaml.safe_dump(staged, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )

    source_env = project_root / ".env"
    target_env = runtime_root / ".env"
    if source_env.exists():
        shutil.copy2(source_env, target_env)
    elif target_env.exists():
        target_env.unlink()

    return RuntimeConfigInfo(
        config_path=str(resolved_config),
        runtime_root=str(runtime_root),
        input_dir=input_dir,
        output_dir=output_dir,
        cache_dir=cache_dir,
        reporting_dir=reporting_dir,
        vector_store_dir=vector_store_uri,
    )


def _print_shell(info: RuntimeConfigInfo) -> None:
    for key, value in asdict(info).items():
        print(f"{key.upper()}={shlex.quote(value)}")


def _print_shell_mapping(data: dict[str, Any]) -> None:
    for key, value in data.items():
        print(f"{key.upper()}={shlex.quote(str(value))}")


async def _count_prompt_tune_chunks_async(
    root_dir: str | Path,
    *,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> int:
    from graphrag.config.load_config import load_config
    from graphrag_chunking.chunker_factory import create_chunker
    from graphrag_input import create_input_reader
    from graphrag_llm.embedding import create_embedding
    from graphrag_storage import create_storage
    from graphrag.index.workflows.create_base_text_units import chunk_document

    graph_config = load_config(root_dir=Path(root_dir))
    if chunk_size is not None and chunk_size > 0:
        graph_config.chunking.size = chunk_size
    if overlap is not None and overlap >= 0:
        graph_config.chunking.overlap = overlap

    embeddings_llm_settings = graph_config.get_embedding_model_config(
        graph_config.embed_text.embedding_model_id
    )
    model = create_embedding(embeddings_llm_settings)
    tokenizer = model.tokenizer
    chunker = create_chunker(graph_config.chunking, tokenizer.encode, tokenizer.decode)
    input_storage = create_storage(graph_config.input_storage)
    input_reader = create_input_reader(graph_config.input, input_storage)
    dataset = await input_reader.read_files()

    chunk_count = 0
    for doc in dataset:
        doc_dict = std_dataclasses.asdict(doc)
        chunk_count += len(chunk_document(doc_dict, chunker))
    return chunk_count


def compute_prompt_tune_limit(
    root_dir: str | Path,
    *,
    requested_limit: int,
    chunk_size: int | None = None,
    overlap: int | None = None,
) -> PromptTuneLimitInfo:
    available_chunks = asyncio.run(
        _count_prompt_tune_chunks_async(
            root_dir,
            chunk_size=chunk_size,
            overlap=overlap,
        )
    )
    if available_chunks <= 0:
        effective_limit = 0
    elif requested_limit <= 0:
        effective_limit = available_chunks
    else:
        effective_limit = min(requested_limit, available_chunks)
    return PromptTuneLimitInfo(
        root=str(Path(root_dir).resolve()),
        available_chunks=available_chunks,
        requested_limit=requested_limit,
        effective_limit=effective_limit,
        chunk_size=chunk_size,
        overlap=overlap,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a GraphRAG config into a runtime root with absolute paths.",
    )
    parser.add_argument(
        "command",
        choices=("stage", "validate-prompts", "validate-config", "prompt-tune-limit"),
        help="The helper operation to execute.",
    )
    parser.add_argument(
        "--config",
        default="settings.yaml",
        help="GraphRAG config file to stage.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Override the configured GraphRAG output directory.",
    )
    parser.add_argument(
        "--cache-dir",
        default=None,
        help="Override the configured GraphRAG cache directory.",
    )
    parser.add_argument(
        "--reporting-dir",
        default=None,
        help="Override the configured GraphRAG reporting directory.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "shell"),
        default="json",
        help="How to print the staged config metadata.",
    )
    parser.add_argument(
        "--for-prompt-tune",
        action="store_true",
        help=(
            "Stage a prompt-tune-safe runtime config. Any prompts_auto/ prompt paths "
            "are rewritten to prompts/ when a matching baseline file exists."
        ),
    )
    parser.add_argument(
        "--root",
        default=None,
        help="GraphRAG runtime root to inspect for prompt-tune operations.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Requested prompt-tune chunk limit.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=None,
        help="Override chunk size when computing prompt-tune chunk counts.",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=None,
        help="Override chunk overlap when computing prompt-tune chunk counts.",
    )
    args = parser.parse_args()

    if args.command == "validate-prompts":
        try:
            validate_prompt_paths(
                args.config,
                project_root=PROJECT_ROOT,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc))
            return 1
        print("Prompt paths validated.")
        return 0

    if args.command == "validate-config":
        try:
            validate_runtime_settings(
                args.config,
                project_root=PROJECT_ROOT,
            )
        except (FileNotFoundError, ValueError) as exc:
            print(str(exc))
            return 1
        print("GraphRAG config validated.")
        return 0

    if args.command == "prompt-tune-limit":
        if not args.root:
            parser.error("--root is required for prompt-tune-limit")
        info = compute_prompt_tune_limit(
            args.root,
            requested_limit=args.limit,
            chunk_size=args.chunk_size,
            overlap=args.overlap,
        )
        if args.format == "shell":
            _print_shell_mapping(asdict(info))
        else:
            print(json.dumps(asdict(info)))
        return 0

    info = stage_runtime_config(
        args.config,
        project_root=PROJECT_ROOT,
        output_override=args.output_dir,
        cache_override=args.cache_dir,
        reporting_override=args.reporting_dir,
        for_prompt_tune=args.for_prompt_tune,
    )

    if args.format == "shell":
        _print_shell(info)
    else:
        print(json.dumps(asdict(info)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
