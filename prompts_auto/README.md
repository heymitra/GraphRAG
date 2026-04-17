# prompts_auto/

Auto-generated GraphRAG prompts produced by `graphrag prompt-tune`.

When a PDF is uploaded in **Auto-Tuned** mode, `auto_tune.sh` calls
`graphrag prompt-tune` which analyses the corpus and writes domain-specific
prompt files here. These prompts are then used during indexing instead of
the generic defaults in `prompts/`.

**Files written here:**
- `extract_graph.txt` — entity/relationship extraction prompt
- `summarize_descriptions.txt` — entity description summarization prompt
- `community_report_*.txt` — community report generation prompts
- `...` — other GraphRAG prompt variants

> **Generated — do not commit.** Each upload in auto-tuned mode may overwrite
> these files. Per-run snapshots are preserved in `prompt_history/`.
