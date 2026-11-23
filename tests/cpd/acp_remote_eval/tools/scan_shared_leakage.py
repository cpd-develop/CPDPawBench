# -*- coding: utf-8 -*-
"""What must never cross out of the grading side, as one runnable rule set.

Two things read this file, and they have to agree:

* the cases behind K2 (``shared`` detail, the rendered report files) and F2 (the
  manifest handed to the agent over ACP), and
* a person pointing it at a captured response before forwarding it::

      python tests/cpd/acp_remote_eval/tools/scan_shared_leakage.py out/report.md

The exit codes are the contract a caller has on this tool, and the three of them
say different things: ``0`` the documents were scanned and are clean, ``1`` at
least one finding, ``2`` the scan did not happen (a missing path, nothing under
it, too much under it).  ``2`` exists because a typo'd directory used to print "0
findings" and exit green, which is the one answer this tool must never give.

The vocabulary lives here and nowhere else on purpose. K2 and F2 used to keep
their own field lists; two lists drift, and when they do the case that still
passes is the one that stopped checking.

A finding is not a proof of leakage and a clean run is not a proof of safety.
This catches the answer key travelling under its own name, label or heading.  It
cannot read a ``.zip`` -- the report bundle is deflate-compressed and holds the
transcripts -- nor rubric prose rewritten into another field, nor a task prompt
that happens to read like a marking scheme.  Those are human calls, and
acceptance 遗留 11 is the sign-off that says who is making them.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

#: Field names that exist only on the grading side.  A document that goes to the
#: leaderboard and carries one of these has been trimmed in the wrong place.
GRADING_SIDE_FIELDS = frozenset(
    {
        "rubric_excerpt",
        "expected_behavior",
        "judge_notes",
        "judge_served_models",
        "workspace_path",
        "transcript_path",
        "downloads",
    }
)

#: The answer key.  No document publishes it -- not one that leaves the service
#: and not one that stays -- because an answer sheet is the one thing a report
#: can never be.  ``judge_prompt`` is on this list rather than the grading-side
#: one because the prompt embeds the rubric: nothing the grader assembles at
#: scoring time belongs in a document at all, and the field does not exist today,
#: which is exactly when a list stops being checked unless it is written down now.
ANSWER_KEY_FIELDS = frozenset(
    {
        "automated_checks",
        "llm_judge_rubric",
        "grading_criteria",
        "grading_code",
        "checker_source",
        "judge_prompt",
    }
)

#: Headings, and only these two shapes.  A heading that merely *mentions* the word
#: ``rubric`` is a task prompt -- "How to write a rubric for the essay" is a real
#: prompt, prompts are echoed into reports and into the manifest, and a
#: check that cries wolf gets ignored the second time it fires on a real run.  So a
#: heading counts when it names a grading-side section, or when the heading *is*
#: the section name.
_LEADING = r"^[ \t]{0,3}#{1,6}[ \t]+"
_SECTION_NAMES = (
    r"expected behavior|rubric excerpt|llm judge rubric|grading criteria"
    r"|automated checks?|judge prompt|answer key"
)
_BARE_SECTION = r"(?:the )?(?:rubric|grading|answer key|expected behavior)"
_HEADING = re.compile(
    _LEADING + rf"(?:[^\n]*\b(?:{_SECTION_NAMES})\b[^\n]*|{_BARE_SECTION})[ \t.]*$",
    re.I | re.M,
)
_LABELLED_FIELDS = (
    r"\b(expected_behavior|rubric_excerpt|llm_judge_rubric"
    r"|automated_checks|grading_criteria|judge_prompt)"
    r"\b[ \t]*[:=]"
)
_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("heading", _HEADING),
    ("label", re.compile(_LABELLED_FIELDS, re.I)),
    ("tag", re.compile(r"<\s*(judge_prompt|rubric|grading_code|automated_checks)\b", re.I)),
)

#: Documents that leave the service for someone else's eyes: a results payload
#: bound for the leaderboard, the manifest the evaluated agent reads.  The whole
#: grading-side vocabulary is banned here.
FORWARDABLE = "forwardable"
#: Documents that stay ours: the detail payload, every rendered report file.
#: Only the answer key is banned -- a rubric excerpt belongs in a report, and a
#: score with no reasoning behind it cannot be argued with.
INTERNAL = "internal"

#: A report body is tens of kilobytes; anything past this is the tool being
#: pointed at something it was never meant to read.  An oversized file is a
#: finding rather than a skip, so "too big to look at" cannot read as "clean".
MAX_DOCUMENT_BYTES = 8 * 1024 * 1024
#: The same reasoning applied to a directory: a whole source tree is a misuse,
#: not a slow pass.
MAX_DOCUMENTS = 500

#: The suffixes a report or a capture arrives with.  ``jsonl`` is on the list
#: because transcripts are written line-delimited, and they are the largest body
#: a report carries.
DOCUMENT_SUFFIXES = frozenset({".json", ".jsonl", ".md", ".html", ".txt"})


def banned_fields(profile: str = FORWARDABLE) -> frozenset[str]:
    """Field names a document of this profile may not carry."""
    if profile == INTERNAL:
        return ANSWER_KEY_FIELDS
    if profile == FORWARDABLE:
        return GRADING_SIDE_FIELDS | ANSWER_KEY_FIELDS
    raise ValueError(f"unknown scan profile {profile!r}")


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _field_findings(profile: str, text: str) -> list[str]:
    """Banned field names, each with the line it sits on.

    The line number is the whole point.  A finding that quoted what it matched
    would copy rubric text into the terminal, and from there into the CI log of
    whoever ran the check.
    """
    found: list[str] = []
    for name in sorted(banned_fields(profile)):
        match = re.search(rf'["\']?{re.escape(name)}["\']?\s*[:=]', text)
        if match is not None:
            found.append(f"field {name} (line {_line_of(text, match.start())})")
    return found


def _marker_findings(text: str) -> list[str]:
    """Heading, label and tag shapes, by line rather than by matched text."""
    found: list[str] = []
    for label, pattern in _MARKERS:
        match = pattern.search(text)
        if match is not None:
            found.append(f"marker {label} (line {_line_of(text, match.start())})")
    return found


def find_in_text(text: str, profile: str = FORWARDABLE) -> list[str]:
    """Findings in one serialized body: field names first, then label shapes.

    The text is searched as text rather than parsed as JSON because the two
    report formats with no JSON shape at all -- ``md`` and ``html`` -- are the
    ones a person forwards, and a trimmed payload can still render a heading.
    """
    findings = _field_findings(profile, text)
    if profile == FORWARDABLE:
        findings += _marker_findings(text)
    return findings


def _paths_of(payload: Any, prefix: str = "") -> dict[str, str]:
    """The first path each key of ``payload`` appears at."""
    found: dict[str, str] = {}
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found.setdefault(str(key), path)
            found.update(_paths_of(value, path))
    elif isinstance(payload, (list, tuple)):
        for index, value in enumerate(payload):
            found.update(_paths_of(value, f"{prefix}[{index}]"))
    return found


def banned_keys(payload: Any, profile: str = FORWARDABLE) -> list[str]:
    """Banned field names still in memory, each with the JSON path it sits at.

    A path rather than a line: a payload has no lines until it is written, and a
    reader of the written document has the key walk to start from.
    """
    paths = _paths_of(payload)
    return [
        f"key {name} (at {paths[name]})"
        for name in sorted(banned_fields(profile) & paths.keys())
    ]


def find_in_payload(payload: Any, profile: str = FORWARDABLE) -> list[str]:
    """Findings for a document still in memory: the keys, then the shapes in text.

    Both halves are needed. A rubric moved under a key that is not on the list is
    invisible to the walk and visible to the marker scan, and a marker is blind to
    a field whose value is a reference to a file we did not forward.
    """
    # Indented so a line number points somewhere a reader can jump to; a
    # one-line dump would make every finding "line 1".
    text = json.dumps(payload, ensure_ascii=False, default=str, indent=1)
    return sorted(set(banned_keys(payload, profile)) | set(find_in_text(text, profile)))


def scan_file(path: Path, profile: str = FORWARDABLE) -> list[str]:
    """Scan one document as it was written out.

    A ``.json`` capture that will not parse is scanned as text rather than
    skipped: half a body is exactly what a truncated download leaves behind, and
    it is the half that may still carry the answer key.  A file that cannot be
    read is a finding for the same reason -- an unreadable document is not a
    clean one.

    A parseable ``.json`` gets the key walk *and* a text scan of the bytes on
    disk.  Scanning the re-serialized body instead would report a line number
    into a dump the reader does not have, and a one-line capture would send them
    to a line four that is not there.
    """
    try:
        size = path.stat().st_size
        if size > MAX_DOCUMENT_BYTES:
            return [f"not scanned: {size} bytes is past the {MAX_DOCUMENT_BYTES} limit"]
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as failure:
        return [f"unreadable: {failure.__class__.__name__}"]
    if path.suffix == ".json":
        try:
            parsed = json.loads(text)
        except ValueError:
            parsed = None
        if parsed is not None:
            return sorted(set(banned_keys(parsed, profile)) | set(find_in_text(text, profile)))
    return find_in_text(text, profile)


def scan_paths(paths: Iterable[Path], profile: str = FORWARDABLE) -> list[str]:
    """Every finding, prefixed by the file it came from."""
    findings: list[str] = []
    for path in paths:
        for finding in scan_file(path, profile):
            findings.append(f"{path}: {finding}")
    return findings


def documents_in(root: Path) -> Sequence[Path]:
    if root.is_file():
        return [root]
    return sorted(
        item
        for item in root.rglob("*")
        if item.is_file() and item.suffix in DOCUMENT_SUFFIXES
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("path", nargs="+", type=Path, help="a document, or a directory of them")
    parser.add_argument("--profile", choices=(FORWARDABLE, INTERNAL), default=FORWARDABLE)
    args = parser.parse_args(argv)

    missing = [str(root) for root in args.path if not root.exists()]
    if missing:
        print(f"nothing was scanned: no such path: {', '.join(missing)}", file=sys.stderr)
        return 2
    targets = [item for root in args.path for item in documents_in(root)]
    if len(targets) > MAX_DOCUMENTS:
        print(
            f"nothing was scanned: {len(targets)} documents is past {MAX_DOCUMENTS}; "
            "point this at a report directory, not a source tree",
            file=sys.stderr,
        )
        return 2
    if not targets:
        suffixes = ", ".join(sorted(DOCUMENT_SUFFIXES))
        roots = ", ".join(str(root) for root in args.path)
        print(f"nothing was scanned: no {suffixes} file under {roots}", file=sys.stderr)
        return 2

    findings = scan_paths(targets, args.profile)
    for line in findings:
        print(line, file=sys.stderr)
    print(f"{len(targets)} document(s) scanned as {args.profile}, {len(findings)} finding(s).")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
