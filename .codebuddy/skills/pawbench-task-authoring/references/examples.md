# Reference Examples

Read the full file before imitating it. Paths are relative to the repo root.

## Hybrid (canonical shape) — read this one first

`data/pawbench-v1.0/tasks/T016_claweval_T002_email_triage.md`

Best overall model: `hybrid` with `automated: 0.35 / llm_judge: 0.65`, a single asset, six
`grade()` keys, a ground-truth list in `## Expected Behavior`, and a two-criterion rubric with
explicit score bands. Its frontmatter is the canonical example to copy.

Excerpt of the frontmatter:

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

## Hybrid with no assets

`data/pawbench-v1.0/tasks/T053_pinchbench_blog.md`

Shows the alternative top-level style (`input_modality`, `external_dependency`,
`workspace_files: []`), a tiered word-count check, a five-signal keyword scorer, and a five-criterion
rubric where every criterion has a **0.0** band.

## `llm_judge` with a large asset tree

`data/pawbench-v1.0/tasks/T124_qwenpawbench_skillhub_0055.md`

101 files staged through `workspace_files`. Note every `source` uses the full file stem
`assets/T124_qwenpawbench_skillhub_0055/...`. Use this as the model whenever a task needs a realistic
project tree.

## `automated` only

`data/pawbench-v1.0/tasks/T036_claweval_T098_pinbench_openclaw_facts.md`,
`data/pawbench-v1.0/tasks/T033_claweval_T088_pinbench_project_bootstrap_plan.md`

Short factuality/plan tasks graded purely by `grade()` — good models for deterministic checks with
no judge.

## Multimodal

`data/pawbench-v1.0/tasks/T013_claweval_M099_su7_price_from_image_zh.md`

Minimal image-understanding task; shows `modality: {type: multimodal, channels: [image]}` plus a
Chinese-language prompt.

## Long-horizon / trap-heavy

`data/pawbench-v1.0/tasks/T086_qwenclawbench_00075_sector_momentum_rotation_backtest_with_data_quality_traps.md`

~33 KB task with planted data-quality traps, a rubric that scores trap detection, and
`timeout_seconds: 1200`. Model for `L3` tasks.

## Inline `workspace_files`

Supported by `_stage_workspace_files` (`path:` + `content:`) but **not used by any v1.0 task**.
Prefer real asset files — they are reviewable in PRs and reproducible.
