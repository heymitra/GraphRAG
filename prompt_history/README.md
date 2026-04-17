# prompt_history/

Per-run prompt snapshots recorded after each successful `graphrag index` run.

## Structure

```
prompt_history/
├── baseline/
│   ├── history.jsonl          # Append-only index of all baseline runs
│   └── {run_id}/
│       ├── manifest.json      # Full run metadata (mode, document, settings, prompt hashes)
│       └── prompts/           # Copies of every prompt file used for this run
│           ├── extract_graph.txt
│           └── ...
└── auto_tuned/
    ├── history.jsonl
    └── {run_id}/
        ├── manifest.json
        └── prompts/
            └── ...
```

## Purpose

Allows the GraphRAG Explorer UI to show exactly which prompts were used for any
given indexing run, so you can compare how prompt changes affect extraction quality.

The `run_id` matches the `prompt_run_id` column in `runs.db`.

> **Generated — do not commit.**
