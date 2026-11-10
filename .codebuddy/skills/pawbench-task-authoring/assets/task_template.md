---
id: __ID__
name: __NAME__
category: __CATEGORY__
grading_type: hybrid
timeout_seconds: 600
grading_weights:
  automated: 0.35
  llm_judge: 0.65
workspace_files: []
labels:
  capabilities:
  - Tool_Use
  - Logic_Reasoning
  modality:
    type: text
    channels: []
  scenario: __SCENARIO__
  complexity: L2
  environment: closed
---

## Prompt

<!-- One or two short paragraphs. State: the goal, the input path(s), the exact output file path,
     the expected output format, and any explicit prohibitions. -->

TODO: write the prompt.

## Expected Behavior

<!-- Numbered steps the agent should follow, then the ground truth / reference answer.
     This section is injected into the judge prompt — the judge cannot invent the ground truth. -->

1. TODO

Reference answer:

- TODO

## Grading Criteria

- [ ] TODO: output file created (output_file_exists)
- [ ] TODO: content matches the reference (content_correct)

## Automated Checks

```python
import json
from pathlib import Path


def grade(transcript: list, workspace_path: str) -> dict:
    result = {
        "output_file_exists": 0.0,
        "content_correct": 0.0,
    }

    out = Path(workspace_path) / "output" / "TODO.json"
    if not out.is_file():
        return result
    result["output_file_exists"] = 1.0

    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        return result

    # TODO: compare against the reference answer
    result["content_correct"] = 1.0
    return result
```

## LLM Judge Rubric

### Criterion 1: TODO (Weight: 60%)

TODO: what to evaluate, referencing the ground truth above.

**Scoring:**
- **1.0**: TODO
- **0.7-0.8**: TODO
- **0.4-0.6**: TODO
- **0.0**: TODO

### Criterion 2: TODO (Weight: 40%)

TODO: quality dimension not already covered by the automated checks.

**Scoring:**
- **1.0**: TODO
- **0.7-0.8**: TODO
- **0.4-0.6**: TODO
- **0.0**: TODO
