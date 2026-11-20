# -*- coding: utf-8 -*-
"""The URL rule that decides what is safe to print, store and forward.

``redact.url_without_credentials`` had no direct case, yet five call sites lean
on it: the endpoint identity that goes into logs and job rows, the CLI's error
message, two report fields and the jobs API response.  Every one of them outlives
the connection it describes, so a credential that survives here is a credential
that gets forwarded.

The shapes below are the ones this feature actually meets: a hosted agent
endpoint carrying ``?key=``, a presigned exchange link whose ``sig`` *is* the
credential, and ``user:pass@`` userinfo.
"""

from __future__ import annotations

import pytest

from pawbench.cpd.acp_remote_eval.acp.client import AcpEndpoint
from pawbench.cpd.acp_remote_eval.redact import url_without_credentials

SECRET = "FAKE-SIG-do-not-use-9d41"


@pytest.mark.parametrize(
    "url",
    [
        f"https://host/agent?key={SECRET}",
        f"https://host/agent?token={SECRET}&other=1",
        f"https://host:8443/agent?sig={SECRET}&se=2026-11-11",
        f"http://host/agent?api_key={SECRET}",
        f"https://host/agent#access_token={SECRET}",
        f"https://host/agent#access_token={SECRET}?key={SECRET}",
    ],
)
def test_a_query_string_never_survives(url: str) -> None:
    """A presigned link's signature is a credential, not decoration."""
    cleaned = url_without_credentials(url)

    assert SECRET not in cleaned
    assert "?" not in cleaned
    assert cleaned.startswith(("https://host", "http://host"))


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"https://{SECRET}@host/agent", "https://host/agent"),
        (f"https://user:{SECRET}@host/agent", "https://host/agent"),
        (f"https://user:{SECRET}@host:8443/agent", "https://host:8443/agent"),
        ("https://host/agent", "https://host/agent"),
        ("https://host", "https://host"),
        ("https://host:8443/agent", "https://host:8443/agent"),
    ],
)
def test_userinfo_goes_and_the_address_stays(url: str, expected: str) -> None:
    assert url_without_credentials(url) == expected


def test_both_halves_at_once() -> None:
    url = f"https://user:{SECRET}@host/agent?key={SECRET}"

    assert url_without_credentials(url) == "https://host/agent"


def test_a_url_without_a_scheme_still_loses_its_query() -> None:
    """The query is stripped before the scheme is looked for, on purpose."""
    assert url_without_credentials(f"host/agent?sig={SECRET}") == "host/agent"


@pytest.mark.parametrize("url", ["", None, "?key=x", f"?{SECRET}"])
def test_nothing_to_describe(url) -> None:
    assert url_without_credentials(url) == ""


def test_cleaning_is_idempotent() -> None:
    url = f"https://user:{SECRET}@host/agent?sig={SECRET}"

    once = url_without_credentials(url)

    assert url_without_credentials(once) == once


def test_the_endpoint_identity_a_log_line_would_carry() -> None:
    """client.py:189 -- this string goes into the job row and the log."""
    endpoint = AcpEndpoint.http(f"https://user:{SECRET}@host/agent?key={SECRET}")

    described = endpoint.describe()

    assert SECRET not in described
    assert described == "http:https://host/agent"


def test_a_password_containing_a_slash_is_not_logged() -> None:
    """Malformed userinfo must not survive as part of the parsed URL path."""
    url = f"https://key:{SECRET}/rest@host/agent"

    cleaned = url_without_credentials(url)

    assert cleaned == "https://[redacted]"
    assert SECRET not in cleaned


def test_a_path_with_an_at_sign_is_redacted_conservatively() -> None:
    assert url_without_credentials("https://host/tasks/a@b") == "https://[redacted]"