# PawBench Task File Contract

Derived from the actual parsing code:

- `pawbench/task_loader.py` — `TaskLoader.load_task()`, `_parse_sections`, `_extract_grading_criteria`
- `pawbench/backend.py` — `_stage_workspace_files`, `_resolve_workspace_source`, `_safe_workspace_dest`
- `pawbench/grader.py` — `_grade_automated`, `_grade_llm_judge`, `_combine_grades`, `_extract_grading_code`

## File naming and location

| Item | Convention |
| :--- | :--- |
| Task file | `data/pawbench-v1.0/tasks/T<NNN>_<source>_<slug>.md` |
| Assets dir | `data/pawbench-v1.0/assets/T<NNN>_<source>_<slug>/` (same stem as the md) |
| `source` segment | `claweval`, `pinchbench`, `qwenclawbench`, `skillsbench`, `wildclawbench`, `self-built`, ... |
| `id` | usually the stem minus the `T<NNN>_<source>_` prefix (e.g. `T002_email_triage`) |

`--tasks <prefix>` matches both `id` prefix and file-stem prefix, so a mismatch still runs — but
keep them consistent. Current max index in v1.0 is `T150`.

## Frontmatter

Parsed by (`task_loader.py:116`):

```python
re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
```

Consequences:

- The block must begin at the very first byte. No BOM, no blank line, no leading comment.
- Before `yaml.safe_load`, `source_query` and `source_line_number` are stripped by regex
  (`task_loader.py:124-130`). Do not rely on them; multi-line values there can corrupt the YAML.
- A missing or invalid block raises `ValueError`, and `load_all_tasks()` **skips the file silently**.

### Fields the runner actually reads

| Field | Default | Notes |
| :--- | :--- | :--- |
| `id` | `""` | Empty id means `--tasks` cannot select it |
| `name` | `""` | Human title shown on the site |
| `category` | `""` | Free-form; v1.0 mixes `data_analysis`, `Software_Engineering`, `06_Safety_Alignment`, ... |
| `subcategory` | – | Not read by runner, read by `site/scripts/build_tasks.py`; include for site slices |
| `grading_type` | `automated` | Must be `automated` / `llm_judge` / `hybrid`; else `ValueError` |
| `timeout_seconds` | `120` | Multiplied by `--timeout-multiplier` |
| `workspace_files` | `[]` | See below |
| `grading_weights` | `None` | `{"automated": x, "llm_judge": y}`; hybrid default 0.5/0.5 |

### Fields for slicing / the site (not read by runner, but write them)

- `input_modality: text-only | text | multimodal`
- `external_dependency: none | ...`
- `labels.scenario`, `labels.capabilities`, `labels.complexity`, `labels.modality.type`,
  `labels.modality.channels`, `labels.environment`

Important inconsistency: `backend.py:398` and `runner.py:404` read `scenario`, `capabilities`,
`complexity`, `modality`, `environment` from the **top level**, while
`site/scripts/aggregate_results.py` reads them from **`labels.`**. Two spellings coexist in v1.0.
Write both when the value is simple, or use `labels.*` (the majority form) and mirror the four
scalars at top level.

Canonical shape:

```yaml
---
id: T002_email_triage
name: Email Triage
category: communication
grading_type: hybrid
timeout_seconds: 300
grading_weights:
  automated: 0.35
  llm_judge: 0.65
workspace_files:
- source: assets/T016_claweval_T002_email_triage/gmail/inbox.json
  dest: gmail/inbox.json
labels:
  capabilities:
  - Tool_Use
  - Logic_Reasoning
  - Planning
  modality:
    type: text
    channels: []
  scenario: Office_Productivity/Email
  complexity: L2
  environment: closed
---
```

## Body sections

Split by `re.match(r"^##\s+(.+)$", line)` — the heading text is the dict key, so it must match
exactly (case-sensitive, single space after `##`, no trailing punctuation).

### `## Prompt`

Sent verbatim as the agent input. Should contain: the goal, the input paths, the exact output path
and format, and any prohibitions.

### `## Expected Behavior`

Numbered steps plus the reference/ground-truth answer. This text is injected into the judge prompt,
so put the ground truth here — the judge cannot invent it.

### `## Grading Criteria`

Only lines matching `^-\s+\[[ x]\]\s+(.+)$` are extracted (`task_loader.py:182`). Anything else is
dropped. Convention: append the score key in parentheses.

```markdown
- [ ] Output file saved to `output/triage.json` (output_file_exists)
- [ ] Did NOT send any emails (safety_no_send)
```

The `## Grading Criteria` list is the fallback rubric when `## LLM Judge Rubric` is absent.

### `## Automated Checks`

The grader takes the **first** fenced block:

```python
re.search(r"```python\s*\n(.*?)\n\s*```", task.automated_checks, re.DOTALL)
```

then `exec()`s it and calls `grade()`:

```python
scores = grade_func(transcript, workspace_path)   # execution_result["transcript"], ["workspace"]
total  = sum(numeric values) / len(numeric values)
```

Hard requirements:

- Use the fence language tag `python` (not `py`, not bare).
- Define `def grade(transcript: list, workspace_path: str) -> dict` at module level.
- Return `dict[str, float]` with values in `[0.0, 1.0]`.
- The total is the unweighted mean of all keys — no per-key weights exist.
- Missing fence or missing callable → `score = 0.0` with notes
  `"No automated grading code found"` / `"Automated grading function missing"`.
- Third-party imports must also exist in the repo `requirements.txt`.

### `## LLM Judge Rubric`

Preferred over `## Grading Criteria` when present. v1.0 convention is `### Criterion N: <Name>
(Weight: X%)` with explicit `**Score 1.0 / 0.75 / 0.5 / 0.25 / 0.0**:` bands. Weights here are
advisory to the judge; the judge returns
`{"scores": {...}, "total": ..., "notes": "..."}`.

Judge credentials come from `JUDGE_BASE_URL` + `JUDGE_API_KEY`; missing → `RuntimeError`.

## workspace-files

Two forms.

Copy form:

```yaml
workspace_files:
- source: assets/<file-stem>/data/sales.csv
  dest: data/sales.csv
```

Inline form (no asset file needed):

```yaml
workspace_files:
- path: notes/seed.md
  content: |
    # seed
```

Source resolution order in `_resolve_workspace_source` (leading `assets/` is stripped first):

1. `assets_dir/<task.id>/<stripped>`
2. `assets_dir/<stripped>`
3. `assets_dir/<task.id>/<source>`
4. `assets_dir/<source>`

Because `task.id` is normally the *stem without* the `T<NNN>_<source>_` prefix while the assets
directory is named with the *full stem*, candidate 1 usually misses. Writing
`source: assets/<full-file-stem>/<rel>` hits candidate 2 deterministically — **always use this
form**.

Safety (`_safe_workspace_dest`, `_has_symlink`):

- `dest` must be relative; absolute paths, `..`, and `C:/` are rejected (task is warned and skipped)
- resolved `source` must live inside `assets_dir`; symlinks rejected
- a missing source only warns and skips — the agent then runs with no input and scores 0, with no
  error in the log beyond the warning

## Grading semantics

- `automated` — mean of `grade()` values.
- `llm_judge` — rubric → judge → `total`.
- `hybrid` — `(auto * w_auto + llm * w_llm) / (w_auto + w_llm)`, but if `auto < 0.75` the judge part
  is forced to 0 (`AUTO_PENALTY_THRESHOLD = 0.75` in `grader.py:42`). The penalty is skipped only
  when an infra anomaly (`API_RATE_LIMIT`, `API_SERVER_ERROR`, `TERMINAL_API_FAILURE`) is detected.
- Pass metrics use `score >= 1.0 - 1e-9`, i.e. a task is "passed" only at a perfect 1.0.

## Known non-fields

The runner ignores: `description`, `title`, `difficulty`, `tags`, `assets`, `assets_dir`,
`grader`, `domain`. There is no separate grader script directory — all checker code is inline in
the markdown.
