# -*- coding: utf-8 -*-
"""Whitelist token verification and the issuing CLI."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from pawbench.cpd.acp_remote_eval.service import auth
from pawbench.cpd.acp_remote_eval.service.auth import (
    SCOPE_ADMIN,
    SCOPE_SUBMIT,
    AuthError,
    Principal,
    StaticConfigVerifier,
    TokenRecord,
    token_sha256,
)


def _expires_in(**kwargs) -> str:
    return (datetime.now(timezone.utc) + timedelta(**kwargs)).isoformat(timespec="seconds")


def _verifier(**overrides) -> tuple[StaticConfigVerifier, dict[str, str]]:
    tokens = {"alice": "alice-token-plain", "bob": "bob-token-plain"}
    records = [
        TokenRecord(
            subject=name,
            token_hash=token_sha256(raw),
            scopes=frozenset(overrides.get("scopes", [SCOPE_SUBMIT]))
            if name == "alice"
            else frozenset([SCOPE_SUBMIT]),
            display_name=name.title(),
            expires_at=overrides.get("expires_at"),
            revoked=bool(overrides.get("revoked", False)) and name == "alice",
        )
        for name, raw in tokens.items()
    ]
    return StaticConfigVerifier(records), tokens


def test_verify_returns_principal_for_known_token() -> None:
    verifier, tokens = _verifier()
    principal = verifier.verify(tokens["alice"])
    assert principal == Principal("alice", "Alice", frozenset({SCOPE_SUBMIT}))
    assert principal.can(SCOPE_SUBMIT)
    assert not principal.can(SCOPE_ADMIN)


def test_unknown_and_empty_tokens_are_indistinguishable() -> None:
    verifier, _ = _verifier()
    for raw in ("", "not-issued-here", token_sha256("alice-token-plain")):
        with pytest.raises(AuthError) as caught:
            verifier.verify(raw)
        assert caught.value.code == "unauthenticated"
        assert caught.value.status == 401, "no 404-style signal that could enumerate subjects"


def test_expired_and_revoked_tokens_are_rejected_with_their_own_code() -> None:
    expired, tokens = _verifier(expires_at=_expires_in(minutes=-1))
    with pytest.raises(AuthError, match="expired") as caught:
        expired.verify(tokens["alice"])
    assert caught.value.code == "expired"

    revoked, tokens = _verifier(revoked=True)
    with pytest.raises(AuthError) as caught:
        revoked.verify(tokens["alice"])
    assert caught.value.code == "revoked"


def test_scope_is_checked_after_the_token_is_accepted() -> None:
    verifier, tokens = _verifier(scopes=[SCOPE_SUBMIT])
    with pytest.raises(AuthError) as caught:
        verifier.verify(tokens["alice"], SCOPE_ADMIN)
    assert caught.value.code == "insufficient_scope"
    assert caught.value.status == 403

    admin_tokens = [
        TokenRecord(
            subject="alice",
            token_hash=token_sha256(tokens["alice"]),
            scopes=frozenset({SCOPE_SUBMIT, SCOPE_ADMIN}),
        )
    ]
    assert StaticConfigVerifier(admin_tokens).verify(tokens["alice"], SCOPE_ADMIN).can(SCOPE_ADMIN)


def test_logs_never_contain_the_token(caplog: pytest.LogCaptureFixture) -> None:
    verifier, tokens = _verifier()
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AuthError):
            verifier.verify("wrong-token")
    joined = " ".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert "wrong-token" not in joined
    assert auth.token_fingerprint("wrong-token") in joined, "the fingerprint is the correlation id"


def test_allowlist_round_trip_stores_only_hashes(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.yaml"
    token = auth.add_subject(path, "li", display_name="Li", scopes=[SCOPE_SUBMIT, SCOPE_ADMIN])
    assert len(token) >= 32

    stored = yaml.safe_load(path.read_text(encoding="utf-8"))
    entry = stored["subjects"][0]
    assert token not in path.read_text(encoding="utf-8"), "plaintext must never hit disk"
    assert entry["token_hash"] == token_sha256(token)
    assert entry["scopes"] == ["admin", "submit"]

    verifier = StaticConfigVerifier.from_file(path)
    assert verifier.verify(token, SCOPE_ADMIN).subject == "li"

    rotated = auth.add_subject(path, "li", scopes=[SCOPE_SUBMIT])
    records = auth.load_records(path)
    assert len(records) == 1, "re-issuing rotates the subject instead of stacking tokens"
    # The running verifier picks the rotation up on its next check.  A token
    # taken off the allowlist has to stop working before the service restarts,
    # or revocation is a request rather than an action.
    with pytest.raises(AuthError):
        verifier.verify(token)
    assert verifier.verify(rotated).subject == "li"

    fresh = StaticConfigVerifier.from_file(path)
    with pytest.raises(AuthError):
        fresh.verify(token)
    assert fresh.verify(rotated).subject == "li"


def test_a_broken_allowlist_edit_keeps_the_last_good_records(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.yaml"
    token = auth.add_subject(path, "li")
    good = path.read_text(encoding="utf-8")
    verifier = StaticConfigVerifier.from_file(path)
    assert verifier.verify(token).subject == "li"

    path.write_text("subjects: [", encoding="utf-8")
    with pytest.raises(yaml.YAMLError):
        auth.load_records(path)
    assert verifier.verify(token).subject == "li", "a truncated edit must not log everyone out"

    path.write_text(good, encoding="utf-8")
    other = auth.add_subject(path, "wu")
    assert verifier.verify(other).subject == "wu", "the next valid edit is picked up"
    assert verifier.verify(token).subject == "li"


def test_revoke_marks_the_record(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.yaml"
    token = auth.add_subject(path, "li")
    assert auth.revoke_subject(path, "li") is True
    assert auth.revoke_subject(path, "ghost") is False
    with pytest.raises(AuthError) as caught:
        StaticConfigVerifier.from_file(path).verify(token)
    assert caught.value.code == "revoked"


def test_unknown_scope_is_refused_at_issue_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown scopes"):
        auth.add_subject(tmp_path / "allowlist.yaml", "li", scopes=["read_all"])


def test_cli_issue_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "allowlist.yaml"
    assert auth.main(["--allowlist", str(path), "add-subject", "--subject", "li"]) == 0
    issued = capsys.readouterr().out.split(":")[1].strip()
    assert auth.main(["--allowlist", str(path), "list"]) == 0
    listed = capsys.readouterr().out
    assert "li" in listed
    assert issued not in listed, "list must not reprint the token"
