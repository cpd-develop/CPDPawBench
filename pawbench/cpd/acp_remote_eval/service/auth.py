# -*- coding: utf-8 -*-
"""Whitelist authentication (design section 6).

The service knows exactly one thing about a caller: whether its token is on the
allowlist and which scopes it carries.  How the token reached the user's
machine is deliberately not modelled here -- that is the pluggable half, and
keeping it out of this interface is what lets the SSO / device-pairing backends
arrive without touching the dashboard or the MCP tools.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import logging
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Protocol, Sequence

import yaml

logger = logging.getLogger(__name__)

SCOPE_SUBMIT = "submit"
SCOPE_ADMIN = "admin"
KNOWN_SCOPES = (SCOPE_SUBMIT, SCOPE_ADMIN)

_TOKEN_BYTES = 32


class AuthError(Exception):
    """Rejected caller.  ``code`` decides the HTTP status, never the message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    @property
    def status(self) -> int:
        return 403 if self.code == "insufficient_scope" else 401


@dataclass(frozen=True)
class Principal:
    subject: str
    display_name: str
    scopes: frozenset[str] = field(default_factory=frozenset)

    def can(self, scope: str) -> bool:
        return scope in self.scopes


@dataclass
class TokenRecord:
    subject: str
    token_hash: str
    scopes: frozenset[str]
    display_name: str = ""
    issued_at: str = ""
    expires_at: str | None = None
    revoked: bool = False


class TokenVerifier(Protocol):
    """Anything that can turn a bearer token into a :class:`Principal`."""

    def verify(self, raw_token: str, scope: str = SCOPE_SUBMIT) -> Principal: ...


def token_sha256(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def token_fingerprint(raw_token: str) -> str:
    """First 8 hex digits of the token hash, safe for logs (design logging rule)."""
    return token_sha256(raw_token)[:8]


def _stat_stamp(path: Path | None) -> tuple[int, int]:
    """(mtime_ns, size) -- enough to notice a rewrite within the same second.

    A missing or unreadable file stamps as ``(0, 0)``, which ``load_records``
    already answers with an empty allowlist rather than an exception.
    """
    if path is None:
        return (0, 0)
    try:
        info = path.stat()
    except OSError:
        return (0, 0)
    return (int(info.st_mtime_ns), int(info.st_size))


class StaticConfigVerifier:
    """Allowlist read from a YAML file.

    Only the SHA-256 of each token is stored, so a leaked allowlist cannot be
    replayed against the service.  Built from a list, the records are fixed;
    built with ``path`` (``from_file``), the file is re-read when its mtime
    changes -- which is what makes a revocation take effect without a restart,
    since a running service is the only thing that has to answer for it.
    """

    def __init__(self, records: Iterable[TokenRecord], path: Path | None = None) -> None:
        self._records: dict[str, TokenRecord] = {record.token_hash: record for record in records}
        self._path = Path(path) if path is not None else None
        self._stamp = _stat_stamp(self._path)

    @classmethod
    def from_file(cls, path: Path | str) -> "StaticConfigVerifier":
        file_path = Path(path)
        return cls(load_records(file_path), path=file_path)

    def _refresh_if_changed(self) -> None:
        """Re-read the allowlist when the file moved, keep it if that failed.

        A half-written file (an editor swapping it, a truncated sync) must not
        log everyone out *and* must not be mistaken for an empty allowlist: the
        last records that parsed stay in force, and the error is what an
        operator sees.
        """
        if self._path is None:
            return
        stamp = _stat_stamp(self._path)
        if stamp == self._stamp:
            return
        self._stamp = stamp
        try:
            records = load_records(self._path)
        except Exception:
            # ``warning``, not ``error``: the service kept authenticating with
            # the records it already had, so nothing failed for the caller --
            # but the operator has to know the edit did not land.
            logger.warning(
                "allowlist re-read failed; keeping the previous records",
                extra={"path": str(self._path)},
                exc_info=True,
            )
            return
        self._records = {record.token_hash: record for record in records}
        logger.info(
            "allowlist re-read",
            extra={"path": str(self._path), "subjects": len({r.subject for r in records})},
        )

    def verify(self, raw_token: str, scope: str = SCOPE_SUBMIT) -> Principal:
        self._refresh_if_changed()
        if not raw_token:
            raise AuthError("unauthenticated", "no bearer token")
        digest = token_sha256(raw_token)
        record = self._records.get(digest)
        if record is None or not hmac.compare_digest(record.token_hash, digest):
            logger.warning("token rejected", extra={"token_fp": token_fingerprint(raw_token)})
            raise AuthError("unauthenticated", "token is not on the allowlist")
        if record.revoked:
            raise AuthError("revoked", "token has been revoked")
        if _is_expired(record.expires_at):
            raise AuthError("expired", "token has expired")
        if scope not in record.scopes:
            raise AuthError(
                "insufficient_scope", f"token is missing the '{scope}' scope"
            )
        return Principal(record.subject, record.display_name or record.subject, record.scopes)


def load_records(path: Path) -> list[TokenRecord]:
    if not path.is_file():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    subjects = raw.get("subjects") if isinstance(raw, dict) else raw
    if not isinstance(subjects, list):
        raise ValueError(f"{path}: expected a list under 'subjects'")
    records = []
    for entry in subjects:
        scopes = frozenset(entry.get("scopes") or [SCOPE_SUBMIT])
        unknown = sorted(scopes - set(KNOWN_SCOPES))
        if unknown:
            raise ValueError(f"{path}: unknown scopes {unknown} for {entry.get('subject')}")
        records.append(
            TokenRecord(
                subject=str(entry["subject"]),
                token_hash=str(entry["token_hash"]),
                scopes=scopes,
                display_name=str(entry.get("display_name") or ""),
                issued_at=str(entry.get("issued_at") or ""),
                expires_at=entry.get("expires_at"),
                revoked=bool(entry.get("revoked")),
            )
        )
    return records


def save_records(path: Path, records: Sequence[TokenRecord]) -> None:
    payload = {
        "subjects": [
            {
                "subject": record.subject,
                "display_name": record.display_name,
                "token_hash": record.token_hash,
                "scopes": sorted(record.scopes),
                "issued_at": record.issued_at,
                "expires_at": record.expires_at,
                "revoked": record.revoked,
            }
            for record in sorted(records, key=lambda item: item.subject)
        ]
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def add_subject(
    path: Path,
    subject: str,
    *,
    display_name: str = "",
    scopes: Iterable[str] = (SCOPE_SUBMIT,),
    expires_at: str | None = None,
) -> str:
    """Append (or rotate) a subject and return the freshly minted token.

    The plaintext token is returned once and never persisted -- the caller has
    to hand it over out of band.
    """
    requested = frozenset(scopes)
    unknown = sorted(requested - set(KNOWN_SCOPES))
    if unknown:
        raise ValueError(f"unknown scopes: {unknown}")
    records = [record for record in load_records(path) if record.subject != subject]
    raw_token = secrets.token_urlsafe(_TOKEN_BYTES)
    records.append(
        TokenRecord(
            subject=subject,
            display_name=display_name,
            token_hash=token_sha256(raw_token),
            scopes=requested,
            issued_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            expires_at=expires_at,
        )
    )
    save_records(path, records)
    logger.info("subject issued", extra={"subject": subject, "scopes": sorted(requested)})
    return raw_token


def revoke_subject(path: Path, subject: str) -> bool:
    records = load_records(path)
    found = False
    for record in records:
        if record.subject == subject:
            record.revoked = True
            found = True
    if found:
        save_records(path, records)
        logger.info("subject revoked", extra={"subject": subject})
    return found


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
    except ValueError:
        return True
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    return expiry <= datetime.now(timezone.utc)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pawbench.cpd.acp_remote_eval.service.auth",
        description="Manage the service token allowlist.",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path(__file__).with_name("allowlist.yaml"),
        help="YAML file holding subject -> token hash records.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("add-subject", help="issue a token and print it once")
    issue.add_argument("--subject", required=True)
    issue.add_argument("--display-name", default="")
    issue.add_argument("--scope", action="append", dest="scopes", default=None)

    revoke = sub.add_parser("revoke", help="mark a subject's token revoked")
    revoke.add_argument("--subject", required=True)

    sub.add_parser("list", help="list subjects (never prints tokens)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    if args.command == "add-subject":
        scopes = args.scopes or [SCOPE_SUBMIT]
        token = add_subject(
            args.allowlist, args.subject, display_name=args.display_name, scopes=scopes
        )
        sys.stdout.write(
            f"token for {args.subject}: {token}\n"
            "This is the only time it is printed. The allowlist stores its hash.\n"
        )
        return 0

    if args.command == "revoke":
        if not revoke_subject(args.allowlist, args.subject):
            sys.stderr.write(f"no such subject: {args.subject}\n")
            return 1
        return 0

    for record in load_records(args.allowlist):
        state = "revoked" if record.revoked else "active"
        sys.stdout.write(
            f"{record.subject}\t{state}\t{sorted(record.scopes)}\t{record.token_hash[:8]}\n"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
