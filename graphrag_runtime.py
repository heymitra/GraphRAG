#!/usr/bin/env python3

from __future__ import annotations

import argparse
import copy
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


@dataclass
class RuntimeConfigInfo:
    config_path: str
    runtime_root: str
    input_dir: str
    output_dir: str
    cache_dir: str
    reporting_dir: str


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


def ensure_prompt_paths_exist(
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


def _runtime_root_for(config_path: Path, *, project_root: Path = PROJECT_ROOT) -> Path:
    try:
        rel = config_path.relative_to(project_root)
        safe_name = "__".join(rel.parts)
    except ValueError:
        safe_name = config_path.name
    safe_name = safe_name.replace(".", "_")
    return (project_root / ".graphrag-runtime" / safe_name).resolve()


def stage_runtime_config(
    config_path: str | Path,
    *,
    project_root: Path = PROJECT_ROOT,
    output_override: str | None = None,
    cache_override: str | None = None,
    reporting_override: str | None = None,
) -> RuntimeConfigInfo:
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

    _absolutize_prompt_paths(staged, project_root=project_root)

    runtime_root = _runtime_root_for(resolved_config, project_root=project_root)
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
    )


def _print_shell(info: RuntimeConfigInfo) -> None:
    for key, value in asdict(info).items():
        print(f"{key.upper()}={shlex.quote(value)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Stage a GraphRAG config into a runtime root with absolute paths.",
    )
    parser.add_argument(
        "command",
        choices=("stage", "validate-prompts"),
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
    args = parser.parse_args()

    if args.command == "validate-prompts":
        try:
            ensure_prompt_paths_exist(
                args.config,
                project_root=PROJECT_ROOT,
            )
        except FileNotFoundError as exc:
            print(str(exc))
            return 1
        print("Prompt paths validated.")
        return 0

    info = stage_runtime_config(
        args.config,
        project_root=PROJECT_ROOT,
        output_override=args.output_dir,
        cache_override=args.cache_dir,
        reporting_override=args.reporting_dir,
    )

    if args.format == "shell":
        _print_shell(info)
    else:
        print(json.dumps(asdict(info)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
