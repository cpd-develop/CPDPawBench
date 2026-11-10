---
name: pawbench-task-authoring
description: Author new PawBench benchmark tasks (data/pawbench-v1.0) end to end — scaffold a task markdown file, build its assets/workspace files, write the automated `grade()` checker and LLM judge rubric, tag the five taxonomy dimensions, and validate against the runner's real parsing contract. This skill should be used when the user asks to create, add, or generate PawBench evaluation tasks or a new PawBench dataset in the pawbench-v1.0 format.
---

# PawBench Task Authoring

## Purpose

Produce task files that the PawBench runner (`pawbench/task_loader.py` + `pawbench/grader.py`) will
actually load and grade. The format has **no JSON Schema and no pydantic model** — the only
authoritative definition is the parsing code, which is permissive: a malformed task is silently
skipped (no frontmatter) or graded 0 (missing `grade()`). So correctness must be enforced by
checklist, not by the loader.

## When to use

- Creating one or more new tasks under `data/pawbench-v1.0/tasks/`
- Generating a new dataset slice / test set in the pawbench-v1.0 format
- Repairing a task that silently scores 0 or never appears in a run

## Running the bundled scripts

All commands below are relative to **this skill's directory**. The scripts locate the PawBench
checkout by walking up from their own location, then from the current directory. When this skill is
installed outside the checkout (a shared `~/.codebuddy/skills` copy, for example), run them with the
working directory set to the checkout, or pass the path explicitly:

```bash
python3 scripts/validate_tasks.py --repo /path/to/PawBench
```

`PAWBENCH_ROOT` is honoured as an environment-level equivalent.

## Workflow

### 1. Gather the task concept

Confirm (or decide and state the assumption) for each of these before writing anything:

1. **What the agent must produce** — a file path in the workspace, a message, a config change?
   Every task needs a concrete, checkable artifact. "Write a good report" is not gradeable.
2. **Grading mode** — `automated`, `llm_judge`, or `hybrid` (v1.0 distribution: 120 hybrid /
   15 automated / 15 llm_judge; default to `hybrid`).
3. **Assets** — does the task need seed files in the workspace? If yes, they go in
   `data/pawbench-v1.0/assets/<file-stem>/` and must be listed in `workspace_files`.
4. **Five taxonomy dimensions** — scenario, capabilities, complexity, modality, environment
   (see `references/taxonomy.md`).
5. **Timeout** — 300 (simple), 600 (default for most), 900–1800 (long-horizon / build tasks).

### 2. Scaffold

```bash
python3 scripts/new_task.py \
  --slug weekly_expense_digest --source self-built \
  --name "Weekly Expense Digest" --category Data_Analytics \
  --grading-type hybrid --timeout 600
```

This allocates the next free `T<NNN>` id, creates
`data/pawbench-v1.0/tasks/T<NNN>_<source>_<slug>.md` from
`assets/task_template.md`, and creates the matching empty
`data/pawbench-v1.0/assets/T<NNN>_<source>_<slug>/` directory.

Never invent a file number by hand — duplicates break `--tasks` filtering. Always use the script.

### 3. Write assets

Put seed files under the created assets directory. Then regenerate the manifest:

```bash
python3 scripts/sync_workspace_files.py \
  data/pawbench-v1.0/tasks/T151_self-built_weekly_expense_digest.md
```

This rewrites the `workspace_files:` block as
`source: assets/<file-stem>/<rel>` + `dest: <rel>` pairs. Keep `source` prefixed with
`assets/<file-stem>/` — that is the only form guaranteed to resolve (see
`references/task_format.md#workspace-files`).

### 4. Write the task body

Fill in the sections in this order. Exact headings are mandatory — the parser matches
`^##\s+(.+)$` literally:

| Order | Heading | Required |
| :--- | :--- | :--- |
| 1 | `## Prompt` | always (becomes the agent's input verbatim) |
| 2 | `## Expected Behavior` | always (fed to the judge) |
| 3 | `## Grading Criteria` | always (`- [ ] text` lines only) |
| 4 | `## Automated Checks` | if `automated` or `hybrid` |
| 5 | `## LLM Judge Rubric` | if `llm_judge` or `hybrid` |

Read `references/task_format.md` for the hard contract of each, and
`references/grading_cookbook.md` for how to write a robust `grade()` and a calibrated rubric.

Prompt-writing rules that matter for score signal:

- Name every input path and every expected output path explicitly.
- State constraints that must NOT be violated (e.g. "do not send any email") — these become
  safety checks in `grade()`.
- Prefer a deterministic output contract (exact filename + JSON schema) over free prose.

### 5. Validate

```bash
python3 scripts/validate_tasks.py \
  data/pawbench-v1.0/tasks/T151_self-built_weekly_expense_digest.md
```

Run it again over the whole directory before opening a PR:

```bash
python3 scripts/validate_tasks.py
```

Fix every `ERROR`. Warnings are advisory but usually indicate a real problem.

### 6. Post-generation chores

- If `grade()` imports a third-party package, add it to the repo `requirements.txt`
  (`tests/test_grader_dependencies.py` enforces this by AST-scanning the python block).
- Regenerate the classification report: `python3 scripts/classify_env.py`
- Regenerate site data: `cd site && npm run build:data`
- Smoke-run the new task: `python3 run_bench.py --tasks T151 --agents qwenpaw`

## Critical constraints

- Frontmatter must start at byte 0 with `---\n`; a BOM, leading blank line, or leading prose makes
  the loader raise `ValueError` and **silently skip** the task.
- `grading_type` must be exactly `automated`, `llm_judge`, or `hybrid`; anything else raises
  `ValueError` at grade time.
- `## Automated Checks` must contain a ```python fence, and the code must define
  `grade(transcript: list, workspace_path: str) -> dict`. Missing either → score 0.
- Score = arithmetic mean of the returned dict's numeric values. Every key is equally weighted
  regardless of name, so do not add filler keys.
- `hybrid` penalty: if the automated part scores `< 0.75`, the LLM judge contribution is zeroed
  (unless an infra anomaly is detected). Keep the automated checks achievable.
- `dest`/`source` must be relative, no `..`, no absolute paths, no symlinks.

## Reference map

- `references/task_format.md` — full field + section contract, with the exact loader regexes
- `references/taxonomy.md` — allowed values for the five dimensions, plus v1.0 distributions
- `references/grading_cookbook.md` — grade() patterns, rubric patterns, anti-patterns
- `references/examples.md` — annotated excerpts from real v1.0 tasks
- `assets/task_template.md` — blank template used by `new_task.py`
