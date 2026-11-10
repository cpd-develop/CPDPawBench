# PawBench Five-Dimension Taxonomy

PawBench uses **Reuse & Tag**: tasks are normalized from existing suites and tagged on five
orthogonal dimensions (README.md `## PawBench Design → Tasks`).

| Dimension | Field | Allowed values |
| :--- | :--- | :--- |
| Scenario | `labels.scenario` | `<L1>/<L2>` |
| Capability | `labels.capabilities` | list, see below |
| Complexity | `labels.complexity` | `L1` / `L2` / `L3` |
| Modality | `labels.modality.type` + `.channels` | `text` / `multimodal` |
| Environment | `labels.environment` | `closed` / `open` |

## Complexity

| Value | Meaning |
| :--- | :--- |
| `L1` | 1–2 steps |
| `L2` | 3–5 steps |
| `L3` | >5 steps, with branches or backtracking |

v1.0 distribution: L3 123, L2 44, L1 18. L3 is heavily over-represented; prefer `L1`/`L2` for new
simple tasks rather than defaulting to L3.

## Capabilities

`Logic_Reasoning`, `Math_Computation`, `Code_Manipulation`, `Tool_Use`, `Skill_Use`, `Planning`,
`Self_Verification`

v1.0 counts (tasks, not occurrences): `Tool_Use` 149, `Planning` 91, `Logic_Reasoning` 89,
`Self_Verification` 59, `Code_Manipulation` 35, `Math_Computation` 34, `Skill_Use` 17.

Guidance: `Tool_Use` belongs on essentially every task. Add `Self_Verification` only when the agent
is expected to check its own output. Add `Skill_Use` only when the task requires discovering or
authoring a skill.

## Modality

```yaml
modality:
  type: text
  channels: []
```

```yaml
modality:
  type: multimodal
  channels:
  - image
```

Non-text channels seen in v1.0: `image`, `video`, `audio`, `gui`. `channels: []` for text tasks
(99 of 124 text tasks write it explicitly). If `type` is `multimodal` **or** `channels` is
non-empty, `scripts/classify_env.py` classifies the task as multimodal.

## Environment

- `closed` — offline and reproducible; all task data is injected into the workspace. (129/150)
- `open` — requires live internet or external SaaS/API. (21/150)

Prefer `closed`. Note the field is read by `scripts/classify_env.py` with
`^\s*environment:\s*(.+?)\s*$` over the whole frontmatter — write it exactly once, at the same
indent level, or the report will pick up an unintended match.

## Scenario vocabulary

Format `<L1>/<L2>`. Existing L1 categories and their L2 values observed in v1.0:

- `Office_Productivity` — `Email`, `Calendar`, `Document`, `Meeting`, `Task_Management`, `Expense`
- `Software_Engineering` — `Code`, `DevOps`, `Database`, `GitHub`
- `Data_Analytics` — `Business_Intelligence`, `Visualization`, `Text_Analytics`
- `Automation_Platform` — `Agent`, `Scheduling`, `Skill`
- `Safety_Alignment` — `Prompt_Injection`, `Data_Protection`, `Harmful_Content`
- `Content_Creation` — `Writing`, `Design`, `Social_Media`, `Video_Audio`
- `Information_Retrieval` — `Market`, `Knowledge_Base`, `Academic`, `Social_Platform`
- `Knowledge` — `QA`
- `Manufacturing_Engineering` — `Quality_Control`
- `Finance_Investment` — `Stock`, `Quantitative_Trading`, `Financial_Report`
- `Legal` — `Contract`

Reuse an existing pair whenever it fits; introduce a new `<L1>/<L2>` only when nothing matches, and
use `Upper_Snake_Case` with `/` as separator.

Frequency leaders: `Software_Engineering/Code` (17), `Data_Analytics/Business_Intelligence` (14),
`Office_Productivity/Document` (10), `Automation_Platform/Agent` (10),
`Safety_Alignment/Prompt_Injection` (8), `Safety_Alignment/Data_Protection` (8),
`Content_Creation/Design` (8).

## Other useful tags

- `category` — free-form; v1.0 uses both snake_case (`data_analysis`) and Title Case
  (`Software_Engineering`). Match the dominant style of the source suite you are imitating.
- `input_modality: text-only | text | multimodal` and `external_dependency: none | ...` are read by
  `site/scripts/build_tasks.py`; include them.
- Safety tasks additionally carry `attack_type:` (e.g.
  `Prompt_Injection/Encoding_Bypass`, `Harmful_Action/Dangerous_System_Command`,
  `Data_Leak_Risk/Content_Injection`, `Harmful_Action/Malicious_Code_Injection`).
