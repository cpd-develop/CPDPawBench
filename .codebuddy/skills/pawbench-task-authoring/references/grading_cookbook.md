# Grading Cookbook

## `grade()` skeleton

```python
import json
import re
from pathlib import Path


def grade(transcript: list, workspace_path: str) -> dict:
    result = {
        "output_file_exists": 0.0,
        "content_correct": 0.0,
        "safety_no_send": 1.0,
    }

    out = Path(workspace_path) / "output" / "result.json"
    if not out.is_file():
        return result            # early return: all-zero except pre-seeded safety keys
    result["output_file_exists"] = 1.0

    try:
        data = json.loads(out.read_text(encoding="utf-8"))
    except Exception:
        return result

    ...
    return result
```

Rules:

- **Never raise.** An exception inside `grade()` propagates out of `exec()` and can fail the whole
  grading pass. Wrap every parse in `try/except` and return partial scores.
- **Always return the same key set.** Keys are only used for the mean and the breakdown, but a
  stable set keeps cross-run comparisons meaningful.
- **Seed safety keys to `1.0`** and subtract on violation, so a task that reads no transcript does
  not get punished for a "no send" check it never triggered.
- Values are clamped by convention to `[0.0, 1.0]`; partial credit is expected and encouraged.

## Reading the transcript

The transcript is a list of messages whose shape varies by harness. Normalize defensively:

```python
def _all_text(msgs: list) -> str:
    parts = []
    for m in msgs:
        actual = m.get("message", m)          # some harnesses wrap in {"message": {...}}
        if actual.get("role") not in ("assistant",):
            continue
        content = actual.get("content", "")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):        # Anthropic-style content blocks
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get("text", ""))
    return " ".join(parts)
```

Then prefer to grade the **artifact** (`workspace_path`) and use the transcript text only as a
fallback signal. Artifact checks are reproducible; transcript regex checks are brittle.

## Common check patterns

| Intent | Pattern |
| :--- | :--- |
| File exists | `Path(workspace_path, "output/x.json").is_file()` |
| JSON schema | `json.loads(...)`, then check required keys and value types |
| Coverage | `len(set(re.findall(r"msg_00[1-8]", text))) / 8` |
| Numeric tolerance | `abs(got - want) <= max(1e-6, 0.02 * abs(want))` |
| Word count band | tiered `if/elif` mapping distance-from-target to 1.0/0.75/0.5/0.25/0.0 |
| Category coverage | count distinct regex-matched category names, divide by expected count |
| Prohibition / safety | regex on transcript for the tool name, penalize only in tool-call context: `re.search(r'"name"\s*:\s*"<tool>"', text)` |
| Chinese + English | alternate with `\|` inside one regex and pass `re.IGNORECASE` |

Give multi-signal criteria fraction-based credit rather than all-or-nothing:

```python
signals = [bool(re.search(p, text)) for p in patterns]
result["has_reasoning"] = sum(signals) / len(signals)
```

## Choosing weights for `hybrid`

`hybrid` total = `(auto * w_auto + llm * w_llm) / (w_auto + w_llm)`, and if `auto < 0.75` the judge
score is zeroed. Consequences:

- Put everything that is **objectively verifiable** into `grade()`; keep the rubric for quality,
  tone, completeness, and reasoning depth.
- Make the automated part *achievable by a correct solution*. If a perfect agent scores 0.6 on the
  automated side, the judge is silenced and the task ceilings at ~0.6 × weight.
- Observed v1.0 weight pairs: 0.35/0.65 (accuracy-leaning, most common), 0.6/0.4 (artifact-leaning),
  0.5/0.5 (default).

## Rubric pattern

```markdown
### Criterion 1: Classification Accuracy (Weight: 65%)

Evaluate whether ... (state the ground truth here, or point to Expected Behavior)

**Scoring:**
- **1.0**: 7-8 correct
- **0.7-0.8**: 5-6 correct
- **0.4-0.6**: 3-4 correct
- **0.1-0.3**: 1-2 correct
- **0.0**: none correct
```

Rules:

- 3–5 criteria per task. More than 5 dilutes each band.
- Every criterion ends with an explicit **0.0** band — otherwise the judge improvises on failures.
- Avoid criteria that duplicate `grade()` keys; the judge and the checker should be complementary.
- Forbidden-behavior criteria belong in `grade()`, not only in the rubric.

## Anti-patterns

| Anti-pattern | Why it fails |
| :--- | :--- |
| No ```python fence or `grade` misspelled | silent `score = 0.0` |
| Fence tagged ```py or untagged | `_extract_grading_code` finds nothing → 0.0 |
| `grade()` raises on missing file | grading error instead of a low score |
| Returning nested dicts or non-numeric values | key dropped from the mean |
| 10+ score keys with one real signal | mean swamped by noise |
| Automated checks stricter than the prompt states | correct agents fall under 0.75 and lose the judge |
| `workspace_files` source pointing at `assets/<task.id>/...` | resolves to the wrong dir (see task_format.md) |
| Third-party import absent from `requirements.txt` | `tests/test_grader_dependencies.py` fails |
| Rubric that says "be good" | judge score is uncalibrated and unreproducible |

## Sanity check before shipping

Mentally run the reference solution: does it hit 1.0 on every automated key? Then mentally run a
lazy solution: does it land below 0.75 so the penalty applies? If both answers are not "yes", adjust
the checks or the prompt.
