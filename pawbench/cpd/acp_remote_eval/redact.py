# -*- coding: utf-8 -*-
"""The one rule for a URL that is safe to print, store or forward.

Split from :mod:`.acp.client` on purpose: the command line refuses to import the
ACP SDK (it would land on every ``--help``), and the service refuses to import
the command line -- so a helper either of them needs cannot live in either.
"""

from __future__ import annotations


def url_without_credentials(url: str) -> str:
    """*url* with its query string and ``user:pass@`` userinfo removed.

    Both halves are secrets that arrive inside a "location": a hosted agent
    endpoint often carries its access key as userinfo or as ``?key=``, and every
    caller here prints an address into a log line, a report or an error message
    that outlives the connection it describes.
    """
    text = str(url or "").split("?", 1)[0].split("#", 1)[0]
    scheme, sep, rest = text.partition("://")
    if not sep:
        return text
    authority, slash, path = rest.partition("/")
    if "@" in path:
        # A slash before userinfo makes the authority ambiguous; do not print
        # any of the address rather than risk retaining a password in the path.
        return f"{scheme}://[redacted]"
    return f"{scheme}://{authority.rsplit('@', 1)[-1]}{slash}{path}"


__all__ = ["url_without_credentials"]
