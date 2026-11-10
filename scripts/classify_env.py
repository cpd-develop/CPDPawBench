# -*- coding: utf-8 -*-
"""Classify pawbench-v1.0 tasks by their frontmatter `environment:` field.

Outputs a markdown report to data/pawbench-v1.0/environment_classification.md.
"""
import re
from pathlib import Path

TASKS_DIR = Path(__file__).resolve().parent.parent / "data" / "pawbench-v1.0" / "tasks"
OUT = Path(__file__).resolve().parent.parent / "data" / "pawbench-v1.0" / "environment_classification.md"

ENV_RE = re.compile(r"^\s*environment:\s*(.+?)\s*$", re.MULTILINE)
FM_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


# Match the standalone `modality:` key (NOT `input_modality:`).
MOD_RE = re.compile(r"(?<!input_)modality:(.*?)(?=\n[^\s]|\Z)", re.DOTALL)
MOD_TYPE_RE = re.compile(r"^\s*type:\s*(.+?)\s*$", re.MULTILINE)
CHANNELS_RE = re.compile(r"^\s*channels:\s*(.*?)(?=\n[^\s]|\n---|\Z)", re.DOTALL)
CH_ITEM_RE = re.compile(r"-\s*([A-Za-z0-9_]+)")


def extract_env(text: str):
    # Only look inside the leading YAML frontmatter block (between the first --- pairs).
    fm = FM_RE.search(text)
    scope = fm.group(1) if fm else text
    m = ENV_RE.search(scope)
    return m.group(1).strip() if m else "(missing)"


INPUT_MOD_RE = re.compile(r"^input_modality:\s*(.+?)\s*$", re.MULTILINE)

# Map top-level input_modality values to (type, channels). Tasks without a
# nested labels.modality block use this single-value field instead.
_INPUT_MAP = {
    "text-only": ("text", []),
    "text": ("text", []),
    "multimodal": ("multimodal", []),
}


def extract_modality(text: str):
    """Return (modality_type, channels_list, source) for a task.

    Priority: nested `labels.modality` block first; fall back to top-level
    `input_modality` (a single value: text-only / text / multimodal).
    """
    fm = FM_RE.search(text)
    scope = fm.group(1) if fm else text
    blk = MOD_RE.search(scope)
    if blk:
        block = blk.group(1)
        mt = MOD_TYPE_RE.search(block)
        mod_type = mt.group(1).strip() if mt else "(missing)"
        cb = CHANNELS_RE.search(block)
        channels = []
        if cb:
            raw = cb.group(1).strip()
            if raw and raw != "[]":
                channels = [c.group(1) for c in CH_ITEM_RE.finditer(raw)]
        return (mod_type, channels, "labels.modality")

    im = INPUT_MOD_RE.search(text)
    if im:
        val = im.group(1).strip()
        if val in _INPUT_MAP:
            return _INPUT_MAP[val] + ("input_modality",)
        return (val, [], "input_modality")

    return ("(missing)", [], "none")


def main():
    files = sorted(TASKS_DIR.glob("*.md"))
    # env buckets
    env_buckets = {}            # env value -> list of (id, name)
    mod_buckets = {}            # modality type -> list of (id, name, channels)
    mod_channel_buckets = {}    # channel -> list of (id, name)
    for f in files:
        text = f.read_text(encoding="utf-8")
        env = extract_env(text)
        mod_type, channels, _src = extract_modality(text)
        mid = re.search(r"^id:\s*(.+?)\s*$", text, re.MULTILINE)
        mname = re.search(r"^name:\s*(.+?)\s*$", text, re.MULTILINE)
        tid = mid.group(1).strip() if mid else f.stem
        tname = mname.group(1).strip() if mname else ""
        env_buckets.setdefault(env, []).append((tid, tname))
        mod_buckets.setdefault(mod_type, []).append((tid, tname, channels))
        for ch in channels:
            mod_channel_buckets.setdefault(ch, []).append((tid, tname))

    total = sum(len(v) for v in env_buckets.values())
    lines = []
    lines.append("# 任务分类报告（Environment × Modality）")
    lines.append("")
    lines.append(f"生成范围：`data/pawbench-v1.0/tasks/`（共 {total} 个任务文件）")
    lines.append("")
    lines.append("> 本文档基于各任务 frontmatter 中的 `environment:` 与 `labels.modality` 字段自动分类。")
    lines.append("")

    # ── Part 1: Environment ────────────────────────────────────────────────
    lines.append("# 第一部分：Environment 分类")
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- `environment: closed` —— 纯本地数据，无需联网（任务数据已随 workspace 注入容器）。")
    lines.append("- `environment: open` —— 需要联网或外部服务（如 web 搜索、外部 mock 服务器、API 调用等）。")
    lines.append("- 其他值 / 缺失 —— 见具体条目。")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| Environment | 任务数 |")
    lines.append("| --- | --- |")
    for env in sorted(env_buckets, key=lambda k: (-len(env_buckets[k]), k)):
        lines.append(f"| {env} | {len(env_buckets[env])} |")
    lines.append("")

    closed = env_buckets.get("closed", [])
    if closed:
        lines.append(f"## 一、纯本地数据（environment: closed）—— 共 {len(closed)} 个")
        lines.append("")
        for tid, tname in closed:
            lines.append(f"- `{tid}` — {tname}")
        lines.append("")

    openl = env_buckets.get("open", [])
    if openl:
        lines.append(f"## 二、需要联网/外部服务（environment: open）—— 共 {len(openl)} 个")
        lines.append("")
        for tid, tname in openl:
            lines.append(f"- `{tid}` — {tname}")
        lines.append("")

    env_others = {k: v for k, v in env_buckets.items() if k not in ("closed", "open")}
    if env_others:
        lines.append("## 三、其他 / 缺失")
        lines.append("")
        for env, items in sorted(env_others.items(), key=lambda kv: (-len(kv[1]), kv[0])):
            lines.append(f"### environment: {env} —— {len(items)} 个")
            lines.append("")
            for tid, tname in items:
                lines.append(f"- `{tid}` — {tname}")
            lines.append("")

    # ── Part 2: Modality ──────────────────────────────────────────────────
    lines.append("")
    lines.append("# 第二部分：Modality（多模态）分类")
    lines.append("")
    lines.append("## 说明")
    lines.append("")
    lines.append("- 取自 frontmatter 的 `labels.modality.type` 与 `labels.modality.channels`。")
    lines.append("- `type: text` 视为纯文本任务；`type: multimodal` 或 channels 非空（image/video/audio/gui 等）视为多模态任务。")
    lines.append("- `channels` 列出该任务实际涉及的输入模态。")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| Modality Type | 任务数 |")
    lines.append("| --- | --- |")
    for mt in sorted(mod_buckets, key=lambda k: (-len(mod_buckets[k]), k)):
        lines.append(f"| {mt} | {len(mod_buckets[mt])} |")
    lines.append("")
    if mod_channel_buckets:
        lines.append("| 输入模态 (channel) | 任务数 |")
        lines.append("| --- | --- |")
        for ch in sorted(mod_channel_buckets, key=lambda k: (-len(mod_channel_buckets[k]), k)):
            lines.append(f"| {ch} | {len(mod_channel_buckets[ch])} |")
        lines.append("")

    # Multimodal = non-text type OR has channels
    multimodal = [(tid, tname, chs) for mt, items in mod_buckets.items()
                  for (tid, tname, chs) in items
                  if (mt not in ("text", "(missing)")) or chs]
    text_only = [(tid, tname) for (tid, tname, chs) in mod_buckets.get("text", [])
                 if not chs]
    missing_mod = mod_buckets.get("(missing)", [])

    lines.append(f"## 一、多模态任务（multimodal / 含非文本通道）—— 共 {len(multimodal)} 个")
    lines.append("")
    for tid, tname, chs in sorted(multimodal, key=lambda x: x[0]):
        ch_str = f" 〔{', '.join(chs)}〕" if chs else ""
        lines.append(f"- `{tid}` — {tname}{ch_str}")
    lines.append("")

    lines.append(f"## 二、纯文本任务（text / 无通道）—— 共 {len(text_only)} 个")
    lines.append("")
    for tid, tname in sorted(text_only, key=lambda x: x[0]):
        lines.append(f"- `{tid}` — {tname}")
    lines.append("")

    if missing_mod:
        lines.append(f"## 三、缺失 modality 字段 —— 共 {len(missing_mod)} 个")
        lines.append("")
        for tid, tname, _ in sorted(missing_mod, key=lambda x: x[0]):
            lines.append(f"- `{tid}` — {tname}")
        lines.append("")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    print(f"Total={total} closed={len(closed)} open={len(openl)} multimodal={len(multimodal)} text_only={len(text_only)} mod_missing={len(missing_mod)}")


if __name__ == "__main__":
    main()
