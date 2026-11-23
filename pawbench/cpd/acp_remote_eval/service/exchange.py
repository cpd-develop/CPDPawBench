# -*- coding: utf-8 -*-
"""Data plane for a remote evaluation run (design section 8).

The evaluated agent runs on someone else's machine and we never touch its
filesystem, so everything crosses as HTTP: fixtures go out as presigned GET
links, results come back as PUT requests carrying a per-run token.

Two rules shape this module:

* The service holds the only trusted copy of the workspace.  A rebuilt
  workspace is *our* fixture layer plus *their* bytes laid over it.
* A submission is untrusted input that a scoring process will read.  Path,
  name, extension and size are checked before anything is written, and what
  passes lands in a quarantine directory first and is moved only afterwards.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import secrets
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import quote

from .config import ExchangeConfig, ServiceConfig
from .schedule import Clock, SystemClock
from .store import Store

logger = logging.getLogger(__name__)

ASSET_SCOPE = "asset"

#: The scope word is inside the signed message, so a fixture link cannot be
#: replayed as a report link even when both name the same job.
REPORT_SCOPE = "report"

#: A run window never shrinks below this, however short the task timeout is.
_MIN_RUN_TTL_SECONDS = 60
_MAX_PATH_DEPTH = 16
_READ_BLOCK_BYTES = 1024 * 1024
_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,80}$")
_UNSAFE_SEGMENTS = frozenset({"", ".", ".."})


class TaskLike(Protocol):
    """The part of :class:`pawbench.task_loader.Task` the data plane needs."""

    task_id: str
    prompt: str
    timeout_seconds: int
    #: ``TaskLoader`` leaves this ``None`` for a task package that declares no
    #: fixtures, which is the common case rather than a malformed task.
    workspace_files: Sequence[Mapping[str, str]] | None


class ExchangeError(ValueError):
    """A data-plane request the service refuses, with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Asset:
    """One fixture file the agent must fetch before it can work."""

    dest: str
    url: str
    sha256: str
    size: int
    expires_at: datetime

    def to_payload(self) -> dict[str, Any]:
        return {
            "dest": self.dest,
            "url": self.url,
            "sha256": self.sha256,
            "size": self.size,
            "expires_at": self.expires_at.isoformat(timespec="seconds"),
        }


@dataclass
class RunGrant:
    """What one run token authorises: uploads for exactly one task attempt."""

    job_id: str
    task_id: str
    attempt: int
    expires_at: datetime
    max_uploads: int
    uploads_used: int = 0

    def is_expired(self, now: datetime) -> bool:
        return _as_utc(now) >= self.expires_at

    def budget_left(self) -> int:
        return max(0, self.max_uploads - self.uploads_used)

    def view(self) -> RunGrant:
        return RunGrant(
            job_id=self.job_id,
            task_id=self.task_id,
            attempt=self.attempt,
            expires_at=self.expires_at,
            max_uploads=self.max_uploads,
            uploads_used=self.uploads_used,
        )


class RunTokenVault:
    """Issues and redeems per-attempt upload tokens.

    Grants live in memory only, and only the hash of a token is kept.  The
    recovery rule for a crashed service is ``failed(recovered)`` and never a
    resume, so a token that outlived its process would authorise uploads
    nobody is tracking.

    Every method holds one lock.  Uploads are accepted from a worker thread
    (``asyncio.to_thread`` in the route) while the runner revokes grants for
    the task it just finished, so an unguarded check-then-increment could
    hand out the same upload slot twice and an unguarded iteration could see
    the dict change size mid-loop.
    """

    def __init__(self) -> None:
        self._grants: dict[str, RunGrant] = {}
        self._lock = threading.Lock()

    def issue(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
        *,
        ttl_seconds: int,
        max_uploads: int,
        now: datetime,
    ) -> tuple[str, RunGrant]:
        token = secrets.token_urlsafe(32)
        instant = _as_utc(now)
        grant = RunGrant(
            job_id=job_id,
            task_id=task_id,
            attempt=attempt,
            expires_at=instant + timedelta(seconds=ttl_seconds),
            max_uploads=max_uploads,
        )
        with self._lock:
            self._drop_expired(instant)
            self._grants[_token_hash(token)] = grant
        return token, grant.view()

    def _drop_expired(self, now: datetime) -> None:
        """Forget grants whose window has already passed.

        Authorising only removes the grant it touches, so the tokens issued
        for the tasks of a run that crashed would otherwise sit in the dict
        for the life of the process.  Sweeping on ``issue`` bounds it at
        "grants for attempts still in flight" without a timer thread.
        """
        dead = [key for key, grant in self._grants.items() if grant.is_expired(now)]
        for key in dead:
            self._grants.pop(key, None)

    def check(
        self, token: str, job_id: str, task_id: str, attempt: int, now: datetime
    ) -> RunGrant:
        """Whether this token may upload here, without spending a slot.

        The route asks this before it buffers the body: a PUT we are going to
        refuse must not be able to make the service hold ``max_bytes_per_artifact``
        for it.
        """
        with self._lock:
            return self._match(token, job_id, task_id, attempt, now).view()

    def authorize(
        self, token: str, job_id: str, task_id: str, attempt: int, now: datetime
    ) -> RunGrant:
        """Spend one upload from the grant, or refuse.

        ``check`` and ``authorize`` are separate because path and size are only
        known once the body has landed, and a refused upload must not cost the
        agent one of its slots -- 64 refused PUTs would otherwise leave the
        real results with ``run_token_spent``.

        The same reason comes back for an unknown and a cross-scoped token:
        differing answers would let anyone enumerate job ids by watching which
        error a guess produces.
        """
        with self._lock:
            grant = self._match(token, job_id, task_id, attempt, now)
            if grant.budget_left() <= 0:
                raise ExchangeError("run_token_spent", "the upload budget is used up")
            grant.uploads_used += 1
            return grant.view()

    def _match(
        self, token: str, job_id: str, task_id: str, attempt: int, now: datetime
    ) -> RunGrant:
        grant = self._grants.get(_token_hash(token or ""))
        if grant is None:
            raise ExchangeError("run_token_invalid", "the run token is not valid here")
        if grant.is_expired(now):
            raise ExchangeError("run_token_expired", "the run token has expired")
        if (grant.job_id, grant.task_id, grant.attempt) != (job_id, task_id, int(attempt)):
            raise ExchangeError("run_token_invalid", "the run token is not valid here")
        return grant

    def status(self, job_id: str, task_id: str, attempt: int) -> list[RunGrant]:
        with self._lock:
            return [
                grant.view()
                for grant in self._grants.values()
                if (grant.job_id, grant.task_id, grant.attempt) == (job_id, task_id, int(attempt))
            ]

    def revoke(self, job_id: str, task_id: str | None = None) -> int:
        with self._lock:
            keys = [
                key
                for key, grant in self._grants.items()
                if grant.job_id == job_id and (task_id is None or grant.task_id == task_id)
            ]
            for key in keys:
                self._grants.pop(key, None)
        return len(keys)


class Presigner:
    """Signs the absolute URLs handed to a machine we do not control.

    The signature, not the caller, decides what a link reaches: it covers the
    resource tuple and the expiry, so a link cannot be edited to name another
    task or another fixture.
    """

    def __init__(self, secret: bytes | None = None) -> None:
        self.secret = secret or secrets.token_bytes(32)

    def signature(self, resource: Sequence[str], expires_at: datetime) -> str:
        message = "|".join([*resource, str(int(expires_at.timestamp()))])
        return hmac.new(self.secret, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(
        self, resource: Sequence[str], expires_at: datetime, signature: str, now: datetime
    ) -> bool:
        if _as_utc(now) >= expires_at:
            return False
        expected = self.signature(resource, expires_at)
        return hmac.compare_digest(expected, str(signature or ""))


@dataclass(frozen=True)
class Upload:
    path: str
    sha256: str
    size: int
    stored_at: Path
    budget_left: int = 0

    def to_payload(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class Rebuild:
    workspace: Path
    fixtures_laid: int
    artifacts_laid: int
    artifact_paths: tuple[str, ...] = field(default_factory=tuple)

    def to_payload(self) -> dict[str, Any]:
        return {
            "workspace": str(self.workspace),
            "fixtures_laid": self.fixtures_laid,
            "artifacts_laid": self.artifacts_laid,
            "artifact_paths": list(self.artifact_paths),
        }


class Exchange:
    """Builds run manifests, takes artifacts back, rebuilds workspaces."""

    def __init__(
        self,
        store: Store,
        service_config: ServiceConfig,
        exchange_config: ExchangeConfig,
        clock: Clock | None = None,
        tokens: RunTokenVault | None = None,
        presigner: Presigner | None = None,
    ) -> None:
        self.store = store
        self.service_config = service_config
        self.config = exchange_config
        self.clock: Clock = clock or SystemClock()
        self.tokens = tokens or RunTokenVault()
        self.presigner = presigner or Presigner()

    # ── manifest ──────────────────────────────────────────────────────────────

    def build_manifest(
        self,
        *,
        job_id: str,
        task: TaskLike,
        dataset_root: Path,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """One JSON document holding everything the agent needs for one task.

        It is embedded in the ACP prompt rather than served behind a URL: the
        served version would need its own authenticated endpoint just to hand
        out the first set of authenticated links.
        """
        now = self.clock.now()
        ttl_seconds = self.run_ttl_seconds(task.timeout_seconds)
        token, grant = self.tokens.issue(
            job_id,
            task.task_id,
            attempt,
            ttl_seconds=ttl_seconds,
            max_uploads=self.config.max_uploads_per_run,
            now=now,
        )
        asset_expiry = self.asset_expires_at(now, grant.expires_at)
        assets = [
            self._asset(job_id, task.task_id, attempt, entry, dataset_root, asset_expiry)
            for entry in _fixtures_of(task)
        ]
        return {
            "protocol": "pawbench-exchange/1",
            "job_id": job_id,
            "task_id": task.task_id,
            "attempt": attempt,
            "prompt": task.prompt,
            "assets": [asset.to_payload() for asset in assets],
            "upload": {
                "method": "PUT",
                # ``{path}`` is substituted by the caller: one PUT per result
                # file, so the path is part of the request, not of the grant.
                "url": f"{self._base_url()}{self.artifacts_path(job_id, task.task_id, attempt)}?path={{path}}",
                "headers": {"Authorization": f"Bearer {token}"},
                "body": "the file bytes, nothing else",
                "budget": grant.budget_left(),
            },
            "expires_at": grant.expires_at.isoformat(timespec="seconds"),
            "deadline_seconds": int(task.timeout_seconds),
        }

    def assets_path(self, job_id: str, task_id: str, attempt: int) -> str:
        return (
            f"/v1/exchange/{quote(_checked_id(job_id, 'job_id'))}/"
            f"{quote(_checked_id(task_id, 'task_id'))}/{int(attempt)}"
        )

    def artifacts_path(self, job_id: str, task_id: str, attempt: int) -> str:
        return f"{self.assets_path(job_id, task_id, attempt)}/artifacts"

    def asset_path(self, job_id: str, task_id: str, attempt: int, dest: str) -> str:
        return f"{self.assets_path(job_id, task_id, attempt)}/assets/{quote(_checked_dest(dest), safe='/~._-')}"

    def _asset(
        self,
        job_id: str,
        task_id: str,
        attempt: int,
        entry: Mapping[str, str],
        dataset_root: Path,
        expires_at: datetime,
    ) -> Asset:
        dest = _checked_dest(str(entry.get("dest", "")))
        source = self.fixture_source(dataset_root, str(entry.get("source", "")))
        digest, size = _digest_and_size(source)
        signature = self.presigner.signature(
            (ASSET_SCOPE, job_id, task_id, str(attempt), dest), expires_at
        )
        url = (
            f"{self._base_url()}{self.asset_path(job_id, task_id, attempt, dest)}"
            f"?expires={int(expires_at.timestamp())}&sig={signature}"
        )
        return Asset(dest=dest, url=url, sha256=digest, size=size, expires_at=expires_at)

    def fixture_source(self, dataset_root: Path, source: str) -> Path:
        """Resolve ``workspace_files[].source`` inside the dataset root."""
        return fixture_source(dataset_root, source)

    def verify_asset_request(
        self,
        *,
        job_id: str,
        task_id: str,
        attempt: int,
        dest: str,
        expires: str | int,
        signature: str,
    ) -> str:
        """Check a presigned GET and return the ``dest`` it authorises."""
        try:
            expires_at = datetime.fromtimestamp(int(expires), tz=timezone.utc)
        except (TypeError, ValueError, OSError) as exc:
            raise ExchangeError("bad_asset_link", "malformed expiry on the asset link") from exc
        checked_dest = _checked_dest(dest)
        resource = (ASSET_SCOPE, job_id, task_id, str(attempt), checked_dest)
        if not self.presigner.verify(resource, expires_at, signature, self.clock.now()):
            raise ExchangeError("asset_link_invalid", "the asset link is not valid")
        return checked_dest

    def fixture_for(self, task: TaskLike, dataset_root: Path, dest: str) -> Path:
        """The file behind a manifest ``dest``, for the route that serves it."""
        return declared_fixture(_fixtures_of(task), dataset_root, dest)

    def session_file(self, job_id: str, task_id: str, attempt: int, dest: str) -> Path:
        """Where a fixture was laid down for one attempt, as the agent saw it.

        The copy, not the dataset: this is the file that was in the working
        directory while the run happened, so it is the one to answer "what did
        the agent actually have in front of it" -- and the only one left when
        the dataset has since been edited or deleted.  A path the upload rules
        would refuse escapes here as the data plane's own error, exactly as a
        download of it would.

        Returns the location whether or not anything is there; the caller
        checks ``is_file`` because "this attempt never lay that fixture down"
        is its answer to give, not this one's.
        """
        return _safe_join(
            self.attempt_dir(job_id, task_id, attempt) / "session",
            _checked_dest(dest),
            create_parent=False,
        )

    # ── artifacts in ──────────────────────────────────────────────────────────

    def check_run_token(self, token: str, job_id: str, task_id: str, attempt: int) -> None:
        """Refuse a PUT this vault will not accept, before its body is read.

        Called from the route: the size limit alone is not enough protection,
        because a caller with a bogus token can still make the service buffer
        a full artifact per request.
        """
        self.tokens.check(token, job_id, task_id, int(attempt), self.clock.now())

    def accept_artifact(
        self,
        *,
        job_id: str,
        task_id: str,
        attempt: int,
        token: str,
        raw_path: str,
        data: bytes,
    ) -> Upload:
        """Validate, quarantine and record one uploaded file."""
        now = self.clock.now()
        path = self.sanitize_output_path(raw_path)

        if len(data) > self.config.max_bytes_per_artifact:
            raise ExchangeError(
                "artifact_too_large",
                f"{path} exceeds {self.config.max_bytes_per_artifact} bytes",
            )

        uploads = self.uploads_dir(job_id, task_id, attempt)
        destination = _safe_join(uploads, path)
        staged = _stage(self.quarantine_dir(job_id, task_id, attempt), data)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, destination)
        finally:
            staged.unlink(missing_ok=True)

        # The slot is spent last, once the bytes are actually stored: an upload
        # refused above cost the run nothing.
        grant = self.tokens.authorize(token, job_id, task_id, attempt, now)
        sha256 = hashlib.sha256(data).hexdigest()
        self.store.record_artifact(
            {
                "job_id": job_id,
                "task_id": task_id,
                "path": path,
                "sha256": sha256,
                "size": len(data),
                "uploaded_at": now.isoformat(timespec="seconds"),
                "kind": "output",
            }
        )
        logger.info(
            "artifact accepted",
            extra={
                "job_id": job_id,
                "task_id": task_id,
                "path": path,
                "size": len(data),
                "sha256_prefix": sha256[:8],
            },
        )
        return Upload(
            path=path,
            sha256=sha256,
            size=len(data),
            stored_at=destination,
            budget_left=grant.budget_left(),
        )

    def sanitize_output_path(self, raw_path: str) -> str:
        """A workspace-relative artifact path, or the reason it is refused.

        Checked here rather than at rebuild time: a refused path never reaches
        disk, so there is nothing to clean up afterwards.
        """
        text = str(raw_path or "").strip().replace("\\", "/")
        if not text:
            raise ExchangeError("empty_path", "the artifact path is empty")
        if "\x00" in text:
            raise ExchangeError("bad_path", "the artifact path contains a NUL byte")
        if text.startswith("/") or re.match(r"^[A-Za-z]:", text):
            raise ExchangeError("path_absolute", f"artifact paths must be relative: {raw_path!r}")

        segments = text.split("/")
        if len(segments) > _MAX_PATH_DEPTH:
            raise ExchangeError("path_too_deep", f"too many path segments: {raw_path!r}")
        if {segment.casefold() for segment in segments} & _UNSAFE_SEGMENTS:
            raise ExchangeError(
                "path_escape", f"the path must stay inside the workspace: {raw_path!r}"
            )
        if any(segment.startswith(".") for segment in segments):
            raise ExchangeError("hidden_path", f"dot files are not accepted: {raw_path!r}")

        name = segments[-1]
        if name.casefold() in self.config.forbidden_names:
            raise ExchangeError(
                "forbidden_name", f"{name} would be collected by the scoring process"
            )
        suffix = Path(name).suffix.casefold()
        if suffix in self.config.forbidden_suffixes:
            raise ExchangeError("forbidden_suffix", f"a {suffix} file is not accepted")
        extension = suffix.lstrip(".")
        if extension not in self.config.allowed_extensions:
            shown = f".{extension}" if extension else "no extension"
            raise ExchangeError(
                "extension_not_allowed", f"{shown} is not an accepted artifact type"
            )
        if not self._prefix_allows(segments):
            raise ExchangeError(
                "prefix_not_allowed", f"{raw_path} is outside the declared output prefixes"
            )
        return "/".join(segments)

    def _prefix_allows(self, segments: Sequence[str]) -> bool:
        for prefix in self.config.allowed_output_prefixes:
            if not prefix:
                return True
            wanted = prefix.split("/")
            if len(segments) > len(wanted) and segments[: len(wanted)] == wanted:
                return True
        return False

    # ── workspace rebuild ─────────────────────────────────────────────────────

    def rebuild_workspace(
        self,
        *,
        job_id: str,
        task: TaskLike,
        dataset_root: Path,
        target: Path,
        attempt: int = 1,
    ) -> Rebuild:
        """Lay the trusted fixtures down first, then the returned artifacts.

        Order matters: for a task that asks for an edit, the agent's version of
        an input file *is* the answer, so uploads always overwrite fixtures.
        """
        workspace = Path(target)
        if workspace.is_symlink():
            raise ExchangeError("symlink_refused", f"refusing to write through a symlink: {workspace}")
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True, exist_ok=True)

        fixtures = 0
        for entry in _fixtures_of(task):
            dest = _checked_dest(str(entry.get("dest", "")))
            source = self.fixture_source(dataset_root, str(entry.get("source", "")))
            _copy_regular_file(source, _safe_join(workspace, dest, create_parent=False))
            fixtures += 1

        rows = self.store.list_artifacts(job_id, task_id=task.task_id, kind="output")
        artifacts = 0
        for row in rows:
            stored = self.upload_path(job_id, task.task_id, attempt, str(row["path"]))
            if stored.is_file():
                _copy_regular_file(stored, _safe_join(workspace, str(row["path"])))
                artifacts += 1
            elif int(row["size"] or 0) > 0:
                # The row says the agent sent bytes and they are not here, so
                # the workspace the grader is about to read is missing part of
                # the answer.  Warning and carrying on scored that as a
                # completed run against an empty file.
                raise ExchangeError(
                    "artifact_missing",
                    f"{row['path']} is recorded as {row['size']} bytes but is not on disk",
                )

        return Rebuild(
            workspace=workspace,
            fixtures_laid=fixtures,
            artifacts_laid=artifacts,
            artifact_paths=tuple(str(row["path"]) for row in rows),
        )

    # ── paths ─────────────────────────────────────────────────────────────────

    def attempt_dir(self, job_id: str, task_id: str, attempt: int) -> Path:
        return (
            Path(self.config.exchange_dir)
            / "jobs"
            / _checked_id(job_id, "job_id")
            / _checked_id(task_id, "task_id")
            / f"attempt-{int(attempt)}"
        )

    def uploads_dir(self, job_id: str, task_id: str, attempt: int) -> Path:
        directory = self.attempt_dir(job_id, task_id, attempt) / "uploads"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def quarantine_dir(self, job_id: str, task_id: str, attempt: int) -> Path:
        directory = self.attempt_dir(job_id, task_id, attempt) / ".quarantine"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def upload_path(
        self, job_id: str, task_id: str, attempt: int, path: str, *, create: bool = True
    ) -> Path:
        """Where one artifact lives, refusing anything that leaves the directory.

        ``create=False`` is for readers: the upload rules make the parent on the
        way in, and a GET that went through the same mkdir would let anybody
        spelling a path decorate the exchange tree with empty directories.
        """
        return _safe_join(
            self.attempt_dir(job_id, task_id, attempt) / "uploads", path, create_parent=create
        )

    # ── reports ───────────────────────────────────────────────────────────────

    def report_path(self, job_id: str, filename: str) -> Path:
        """Where one generated report lives, under the exchange directory.

        The name is validated as a single path segment, so a report can only
        ever be written inside ``reports/<job_id>/`` -- the bytes a whitelisted
        caller asked us to render stay out of everybody else's directory.
        """
        directory = Path(self.config.exchange_dir) / "reports" / _checked_id(job_id, "job_id")
        directory.mkdir(parents=True, exist_ok=True)
        return directory / _checked_id(filename, "filename")

    def report_link(self, job_id: str, filename: str) -> str:
        """A presigned GET for a report file -- same TTL as a fixture link.

        The route that hands out the link returns it instead of the bytes: a
        report is rendered once and then fetched by whoever opens it, and a
        download that goes through the service process would turn a 64 MB zip
        into a request that holds the event loop's attention.
        """
        expires_at = self.report_expires_at()
        checked_job = _checked_id(job_id, "job_id")
        checked_name = _checked_id(filename, "filename")
        signature = self.presigner.signature(
            (REPORT_SCOPE, checked_job, checked_name), expires_at
        )
        return (
            f"{self._base_url()}/v1/reports/{quote(checked_job)}/{quote(checked_name)}"
            f"?expires={int(expires_at.timestamp())}&sig={signature}"
        )

    def report_expires_at(self) -> datetime:
        return _as_utc(self.clock.now()) + timedelta(seconds=self.config.asset_url_ttl_seconds)

    def verify_report_request(
        self, *, job_id: str, filename: str, expires: str | int, signature: str
    ) -> str:
        """Check a presigned report GET and return the filename it authorises."""
        checked = _checked_id(filename, "filename")
        try:
            expires_at = datetime.fromtimestamp(int(expires), tz=timezone.utc)
        except (TypeError, ValueError, OSError) as exc:
            raise ExchangeError("bad_report_link", "malformed expiry on the report link") from exc
        resource = (REPORT_SCOPE, _checked_id(job_id, "job_id"), checked)
        if not self.presigner.verify(resource, expires_at, signature, self.clock.now()):
            raise ExchangeError("report_link_invalid", "the report link is not valid")
        return checked

    def drop_attempt(self, job_id: str, task_id: str, attempt: int) -> None:
        """Remove the bytes exchanged for one attempt; the recorded rows stay."""
        shutil.rmtree(self.attempt_dir(job_id, task_id, attempt), ignore_errors=True)
        self.tokens.revoke(job_id, task_id)

    def run_ttl_seconds(self, timeout_seconds: int) -> int:
        """How long a run's links and token stay valid (design section 13)."""
        multiplier = float(self.service_config.exchange_ttl_multiplier)
        return max(_MIN_RUN_TTL_SECONDS, int(timeout_seconds * multiplier))

    def asset_expires_at(self, now: datetime, run_expires_at: datetime) -> datetime:
        """Fixture links live for ``exchange.asset_url_ttl_seconds``, capped
        by the run: a long task timeout should not leave a downloadable input
        link valid for hours after the attempt is over."""
        link_expiry = _as_utc(now) + timedelta(seconds=self.config.asset_url_ttl_seconds)
        return min(link_expiry, _as_utc(run_expires_at))

    def _base_url(self) -> str:
        # The configured address, never the request Host: a caller-controlled
        # host would put a caller-controlled origin inside the presigned links.
        return self.service_config.public_base_url


def _fixtures_of(task: TaskLike) -> list[Mapping[str, str]]:
    """The fixtures a task declares, in manifest order."""
    return list(task.workspace_files or [])


def _checked_dest(dest: str) -> str:
    text = str(dest or "").strip().replace("\\", "/")
    segments = text.split("/")
    if not text or {segment.casefold() for segment in segments} & _UNSAFE_SEGMENTS:
        raise ExchangeError(
            "bad_dest", f"fixture destination must be workspace-relative: {dest!r}"
        )
    if any(segment.startswith(".") for segment in segments):
        raise ExchangeError("bad_dest", f"fixture destination is a dot file: {dest!r}")
    return "/".join(segments)


def fixture_source(dataset_root: Path, source: str) -> Path:
    """Resolve ``workspace_files[].source`` inside the dataset root.

    Module level rather than a method because two callers ask it and neither
    owns the other: the data plane serves a fixture to a run, and the catalogue
    shows a fixture in a dataset that has never been run.  A route that could
    reach a file the download route refuses would make the second caller a
    looser door than the first, so the resolution -- and therefore the refusal
    of absolute paths, dot segments and symlinks out of the tree -- happens in
    one function.
    """
    text = str(source or "").strip().replace("\\", "/")
    if not text or text.startswith("/"):
        raise ExchangeError(
            "bad_asset_source", f"asset source must be dataset-relative: {source!r}"
        )
    segments = text.split("/")
    if any(segment in _UNSAFE_SEGMENTS for segment in segments):
        raise ExchangeError(
            "bad_asset_source", f"asset source escapes the dataset: {source!r}"
        )
    root = Path(dataset_root).resolve()
    path = root.joinpath(*segments).resolve()
    if root not in path.parents:
        raise ExchangeError(
            "bad_asset_source", f"asset source leaves the dataset root: {source!r}"
        )
    if not path.is_file():
        raise ExchangeError("asset_not_found", f"fixture file missing: {source}")
    return path


def declared_fixture(
    workspace_files: Sequence[Mapping[str, str]] | None, dataset_root: Path, dest: str
) -> Path:
    """The file behind one manifest ``dest``, whoever is asking for it.

    Only a declared ``dest`` resolves: the dataset directory also holds task
    markdown, other tasks' fixtures and whatever an author left there, and a
    lookup that took any relative path would be a browser over all of it.
    """
    wanted = _checked_dest(dest)
    for entry in workspace_files or ():
        try:
            declared = _checked_dest(str(entry.get("dest", "")))
        except ExchangeError:
            # One malformed line in a manifest is not a reason to hide the
            # other files: a list of attachments whose answer depends on which
            # entry happens to come first is not an answer.  The requested
            # ``dest`` was checked above, so skipping a bad entry cannot turn
            # an unsafe path into a servable one.
            continue
        if declared == wanted:
            return fixture_source(dataset_root, str(entry.get("source", "")))
    raise ExchangeError("asset_unknown_dest", f"{dest} is not an asset of this task")


def _checked_id(value: str, label: str) -> str:
    text = str(value or "")
    if not _ID_RE.match(text) or text in _UNSAFE_SEGMENTS:
        # ``.`` and ``..`` pass the character class, and these ids are joined
        # straight into the exchange tree -- where ``drop_attempt`` and
        # ``rebuild_workspace`` rmtree whatever the segment resolves to.
        raise ExchangeError(
            "bad_identifier", f"{label} is not usable as a path segment: {value!r}"
        )
    return text


def _safe_join(root: Path, relative: str, *, create_parent: bool = True) -> Path:
    base = Path(root).resolve()
    candidate = base.joinpath(*relative.split("/"))
    if candidate.is_symlink():
        raise ExchangeError("symlink_refused", f"refusing to write through a symlink: {candidate}")
    resolved = candidate.resolve()
    if base not in resolved.parents:
        raise ExchangeError("path_escape", f"{relative} escapes {base}")
    if create_parent:
        resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _copy_regular_file(source: Path, destination: Path) -> None:
    for path in (source, destination):
        if path.is_symlink():
            raise ExchangeError("symlink_refused", f"symlinks are never copied: {path}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def _stage(quarantine: Path, data: bytes) -> Path:
    """Write to the quarantine directory and fsync before anything is moved."""
    staged = quarantine / f"{secrets.token_hex(8)}.part"
    with open(staged, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    if staged.is_symlink():  # pragma: no cover - only reachable if /tmp is hostile
        staged.unlink(missing_ok=True)
        raise ExchangeError("symlink_refused", f"staged artifact is a symlink: {staged}")
    return staged


def _digest_and_size(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(_READ_BLOCK_BYTES), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
