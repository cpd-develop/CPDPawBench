# -*- coding: utf-8 -*-
"""One file, as much of it as a dialog can show, and what kind of file it is.

Two readers answer the same question about a path: the job views (an artifact
the agent wrote back, a fixture the task handed it) and the catalogue (the
fixture sitting in a dataset, before any run exists).  The decision is not the
same kind of thing as either of those views -- it is a policy about bytes, and
it lives here so a cap or an image whitelist cannot be tightened in one place
and left loose in the other.

Nothing here reads a database or a job.  Given a path it returns a dict; the
caller is responsible for having decided that the caller may see that path.
"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any

#: How much one preview may carry.  An artifact can be 64 MB (the exchange cap),
#: and this answer is rendered inline in a dialog, so the ceiling lives here
#: rather than in the browser: the point of a preview is that the bytes never
#: cross the wire in full.  Text is cut, not refused -- half a log still explains
#: the failure -- and the answer says which it is.
PREVIEW_TEXT_BYTES = 256 * 1024
PREVIEW_IMAGE_BYTES = 2 * 1024 * 1024

#: The three shapes a preview can take.  ``binary`` is a real answer, not a
#: failure: a spreadsheet is neither text nor drawable, and "download it" is
#: what a reader can act on.
PREVIEW_TEXT = "text"
PREVIEW_IMAGE = "image"
PREVIEW_BINARY = "binary"

#: Extensions the browser can draw, as a whitelist rather than by sniffing every
#: format: an ``<img>`` handed bytes it cannot decode shows a broken icon, which
#: is a worse answer than naming the file and offering the download.
_IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".svg": "image/svg+xml",
}

#: How much of a file is read to decide whether it is text at all.  Small enough
#: that a wrong guess costs nothing, large enough to clear a header.
_SNIFF_BYTES = 4096


def preview_of(target: Path, raw_path: str) -> dict[str, Any]:
    """One file, as much of it as a dialog can show, and what it is.

    Three answers, decided in this order: an image extension is drawn, anything
    else that reads as UTF-8 is shown as text, and the rest is named a binary so
    the reader is sent to the download instead of to a wall of replacement
    characters.  ``shown_bytes`` is what came back, not what the file is --
    those differ whenever a cap applied, and a reader who sees the two numbers
    can tell whether they are looking at the whole file.
    """
    size = target.stat().st_size
    suffix = target.suffix.lower()
    if suffix in _IMAGE_TYPES:
        media_type = _IMAGE_TYPES[suffix]
        if size > PREVIEW_IMAGE_BYTES:
            # ``image`` is still the truth about the file; nothing is inlined.
            return {
                "path": raw_path,
                "kind": PREVIEW_IMAGE,
                "media_type": media_type,
                "bytes": size,
                "shown_bytes": 0,
                "truncated": True,
            }
        data = target.read_bytes()
        return {
            "path": raw_path,
            "kind": PREVIEW_IMAGE,
            "media_type": media_type,
            "bytes": size,
            "shown_bytes": len(data),
            "truncated": False,
            "data_url": f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}",
        }
    if not _decodes_as_text(_head_of(target, _SNIFF_BYTES)):
        return {
            "path": raw_path,
            "kind": PREVIEW_BINARY,
            "media_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
            "bytes": size,
            "shown_bytes": 0,
            "truncated": False,
        }
    trimmed = size > PREVIEW_TEXT_BYTES
    data = _head_of(target, PREVIEW_TEXT_BYTES) if trimmed else target.read_bytes()
    return {
        "path": raw_path,
        "kind": PREVIEW_TEXT,
        "media_type": "text/plain; charset=utf-8",
        "bytes": size,
        "shown_bytes": len(data),
        "truncated": trimmed,
        # ``replace`` rather than refusing: the alternative is answering
        # "binary" for a file that is text with one bad byte in it.
        "text": data.decode("utf-8", "replace"),
    }


def _head_of(path: Path, limit: int) -> bytes:
    with path.open("rb") as handle:
        return handle.read(limit)


def _decodes_as_text(head: bytes) -> bool:
    """Whether a file's opening bytes read as UTF-8.

    Sniffed rather than taken from the suffix: a ``.txt`` that is really a zip
    decoded into mojibake is a worse answer than being told it is a binary.  A
    character straddling the sniff window is not evidence of anything, which is
    what the last-few-bytes allowance is for -- ``unexpected end of data`` is
    what a cut multi-byte sequence raises.
    """
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as exc:
        if exc.reason != "unexpected end of data" or exc.start < len(head) - 3:
            return False
    return True
