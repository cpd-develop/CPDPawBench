# -*- coding: utf-8 -*-
"""SQLite persistence for jobs, datasets and task results.

Standard library only (design section 15): the queue and the whitelist need
transactions and a long-lived process, not an ORM.

Every public method is synchronous.  Callers running inside the service event
loop must go through ``asyncio.to_thread`` so a write never stalls a request.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from types import TracebackType
from typing import Any, Iterable, Sequence

logger = logging.getLogger(__name__)

_JSON_COLUMNS = frozenset(
    {
        "env_fingerprint",
        "categories",
        "task_ids",
        "filter_spec",
        "resolved_task_ids",
        "resolved_from",
        "automated_breakdown",
        "judge_notes",
        "judge_served_models",
        "subject_model_reported",
    }
)

#: How long a statement waits for the write lock before giving up, in ms.
_BUSY_TIMEOUT_MS = 5000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                  TEXT PRIMARY KEY,
    submitter           TEXT NOT NULL,
    token_subject       TEXT NOT NULL,
    purpose             TEXT,
    product             TEXT,
    acp_url             TEXT NOT NULL,
    window_kind         TEXT NOT NULL,
    not_before          TEXT,
    not_after           TEXT,
    status              TEXT NOT NULL,
    queue_pos           REAL NOT NULL,
    max_tasks           INTEGER,
    concurrency         INTEGER,
    env_fingerprint     TEXT,
    created_at          TEXT NOT NULL,
    scheduled_at        TEXT,
    started_at          TEXT,
    finished_at         TEXT,
    error               TEXT,
    result_summary_path TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_pos ON jobs (status, queue_pos);
CREATE INDEX IF NOT EXISTS idx_jobs_submitter ON jobs (submitter);

-- Which process is running a 'running' job.  jobs.status cannot answer that on
-- its own: a process that dies writes nothing, so this row is what tells a
-- restart which jobs to settle and which to leave alone.
CREATE TABLE IF NOT EXISTS job_leases (
    job_id      TEXT PRIMARY KEY,
    owner       TEXT NOT NULL,
    beat_at     TEXT NOT NULL,
    ttl_seconds REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS job_datasets (
    job_id              TEXT NOT NULL,
    dataset_id          TEXT NOT NULL,
    dataset_kind        TEXT NOT NULL,
    requested_by        TEXT,
    resolved_task_ids   TEXT,
    PRIMARY KEY (job_id, dataset_id)
);

CREATE TABLE IF NOT EXISTS datasets (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    owner       TEXT NOT NULL,
    kind        TEXT NOT NULL,
    description TEXT,
    categories  TEXT,
    task_ids    TEXT,
    filter_spec TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    task_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS dataset_categories (
    name        TEXT PRIMARY KEY,
    description TEXT,
    created_by  TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_tasks (
    job_id                  TEXT NOT NULL,
    task_id                 TEXT NOT NULL,
    attempt                 INTEGER NOT NULL DEFAULT 1,
    status                  TEXT NOT NULL,
    workspace_path          TEXT,
    score                   REAL,
    grading_type            TEXT,
    artifact_count          INTEGER NOT NULL DEFAULT 0,
    protocol_written        INTEGER NOT NULL DEFAULT 0,
    out_of_band_count       INTEGER NOT NULL DEFAULT 0,
    failure_reason          TEXT,
    resolved_from           TEXT,
    started_at              TEXT,
    finished_at             TEXT,
    duration_s              REAL,
    automated_breakdown     TEXT,
    judge_notes             TEXT,
    judge_served_models     TEXT,
    subject_model_reported  TEXT,
    transcript_path         TEXT,
    artifact_manifest_path  TEXT,
    -- What ties one attempt to what the agent did.  ``trace_id`` is ours and
    -- appears in every log line of the attempt, so an operator can jump from a
    -- report row to the stderr that explains it; ``session_id`` is the agent's
    -- own handle and is what its own logs are indexed by.
    session_id              TEXT,
    trace_id                TEXT,
    PRIMARY KEY (job_id, task_id, attempt)
);

CREATE TABLE IF NOT EXISTS artifacts (
    job_id      TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    path        TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    size        INTEGER NOT NULL,
    uploaded_at TEXT NOT NULL,
    kind        TEXT NOT NULL,
    PRIMARY KEY (job_id, task_id, path)
);
"""

#: Columns added after the first database was written.
#:
#: ``CREATE TABLE IF NOT EXISTS`` is a no-op on a file that already has the
#: table, so a new column in ``_SCHEMA`` reaches fresh databases and silently
#: never reaches the one an operator is running.  This is the running list the
#: constructor reconciles; SQLite has no ``ADD COLUMN IF NOT EXISTS``, hence the
#: caught error rather than a lookup.
_ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("job_tasks", "session_id", "TEXT"),
    ("job_tasks", "trace_id", "TEXT"),
)


def _reconcile_columns(conn: sqlite3.Connection) -> None:
    for table, column, sql_type in _ADDED_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc).lower():
                raise


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_JOB_COLUMNS = frozenset(
    {
        "submitter",
        "token_subject",
        "purpose",
        "product",
        "acp_url",
        "window_kind",
        "not_before",
        "not_after",
        "status",
        "queue_pos",
        "max_tasks",
        "concurrency",
        "env_fingerprint",
        "created_at",
        "scheduled_at",
        "started_at",
        "finished_at",
        "error",
        "result_summary_path",
    }
)

_JOB_TASK_COLUMNS = frozenset(
    {
        "status",
        "workspace_path",
        "score",
        "grading_type",
        "artifact_count",
        "protocol_written",
        "out_of_band_count",
        "failure_reason",
        "resolved_from",
        "started_at",
        "finished_at",
        "duration_s",
        "automated_breakdown",
        "judge_notes",
        "judge_served_models",
        "subject_model_reported",
        "transcript_path",
        "artifact_manifest_path",
        "session_id",
        "trace_id",
    }
)


class UnknownColumn(ValueError):
    """Raised when an update names a column that does not exist.

    ``update_job`` interpolates column names into SQL, so the whitelist is what
    keeps a request body from becoming a statement of the caller's choosing.
    """


def _checked_update_fields(allowed: frozenset[str], fields: dict[str, Any]) -> list[str]:
    unknown = sorted(set(fields) - allowed)
    if unknown:
        raise UnknownColumn(f"columns not updatable: {unknown}")
    return list(fields)


class Store:
    """One SQLite connection guarded by a lock.

    WAL keeps the reader side (dashboard polling, MCP tools) from blocking the
    writer side (the dispatch loop); the lock exists because a single
    connection is not safe to share across the thread pool.
    """

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        # WAL lets a second connection (the dashboard, the MCP tools) read
        # without blocking this one, but two writers still queue -- and the
        # default queue length is zero, so the loser of the race would raise
        # "database is locked" out of the middle of a scheduler tick.
        self._conn.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        self._conn.executescript(_SCHEMA)
        _reconcile_columns(self._conn)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "Store":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    # ── write helpers ─────────────────────────────────────────────────────────

    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock, self._conn:
            return self._conn.execute(sql, params)

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self._lock, self._conn:
            self._conn.executemany(sql, rows)

    def transition_job(
        self, job_id: str, *, from_status: str, to_status: str, **fields: Any
    ) -> bool:
        """Move one job between states, and say whether it actually moved.

        The guard is the reason this exists instead of :meth:`update_job`: the
        queue reads the running set and then promotes candidates, and between
        those two statements a cancel -- or another tick -- can change the row.
        Writing ``WHERE status = from_status`` makes the read part of the write,
        so a job that was cancelled a moment ago cannot be revived as running.

        :meth:`admit_job` is the version that also holds the concurrency limits.
        """
        values: dict[str, Any] = {"status": to_status, **fields}
        columns = _checked_update_fields(_JOB_COLUMNS, values)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        params = [_to_stored(column, values[column]) for column in columns]
        params.extend([job_id, from_status])
        with self._lock, self._conn:
            cursor = self._conn.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ? AND status = ?", params
            )
            return cursor.rowcount == 1

    def admit_job(
        self,
        job_id: str,
        *,
        started_at: str,
        max_concurrent_jobs: int,
        max_running_per_user: int,
    ) -> bool:
        """Start one queued job if, and only if, a slot is genuinely free.

        Both limits are counted inside the statement rather than from a
        snapshot the caller took earlier: with the API threads and the tick
        thread writing at the same time, a snapshot is a promise about a row
        count that has already moved, and the promise is what over-books the
        service.  The ``status = 'queued'`` guard closes the other half -- a job
        canceled while this statement was waiting for the lock stays canceled.

        The per-user count comes from the row's own ``submitter``, not from an
        argument: a caller that passes the wrong subject would silently disable
        the limit instead of refusing the job.
        """
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE jobs
                   SET status = 'running', started_at = ?
                 WHERE id = ?
                   AND status = 'queued'
                   AND (SELECT COUNT(*) FROM jobs WHERE status = 'running') < ?
                   AND (SELECT COUNT(*) FROM jobs AS mine
                         WHERE mine.status = 'running'
                           AND mine.submitter = jobs.submitter) < ?
                """,
                (
                    started_at,
                    job_id,
                    int(max_concurrent_jobs),
                    int(max_running_per_user),
                ),
            )
            return cursor.rowcount == 1

    # ── leases ────────────────────────────────────────────────────────────────

    def acquire_lease(
        self, job_id: str, *, owner: str, beat_at: str, ttl_seconds: float
    ) -> bool:
        """Claim the lease that says which process is running this job.

        The row is the only durable answer to "is this ``running`` job actually
        being run, or is it what a restart left behind?" -- ``jobs.status`` alone
        cannot tell, because a process that dies never writes again.  Re-taking
        your own lease is a refresh; taking someone else's is refused until their
        beat goes stale, which is what keeps two services pointed at one database
        from running the same job twice.

        ``julianday`` rather than string comparison: the beats are ISO strings
        with whatever UTC offset each process was configured for, and those do
        not sort.
        """
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO job_leases (job_id, owner, beat_at, ttl_seconds)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE
                   SET beat_at = excluded.beat_at,
                       owner = excluded.owner,
                       ttl_seconds = excluded.ttl_seconds
                 WHERE job_leases.owner = excluded.owner
                    OR (julianday(excluded.beat_at) - julianday(job_leases.beat_at))
                       * 86400.0 > job_leases.ttl_seconds
                """,
                (job_id, owner, beat_at, float(ttl_seconds)),
            )
            return cursor.rowcount == 1

    def beat_lease(self, job_id: str, *, owner: str, beat_at: str) -> bool:
        """Refresh a lease we already hold; false means it is no longer ours."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "UPDATE job_leases SET beat_at = ? WHERE job_id = ? AND owner = ?",
                (beat_at, job_id, owner),
            )
            return cursor.rowcount == 1

    def release_lease(self, job_id: str, *, owner: str) -> bool:
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM job_leases WHERE job_id = ? AND owner = ?",
                (job_id, owner),
            )
            return cursor.rowcount == 1

    def lease_owner(self, job_id: str) -> str | None:
        """Who holds the lease now, which is the part a refusal has to name.

        Read separately from :meth:`acquire_lease` because a lost race is a
        deployment fault, and "someone else has it" without the someone is the
        half of the report that tells the operator which two processes to look at.
        """
        row = self.query_one("SELECT owner FROM job_leases WHERE job_id = ?", (job_id,))
        return str(row["owner"]) if row else None

    def orphan_running_jobs(self, now_iso: str) -> list[str]:
        """``running`` jobs whose lease is missing or gone stale."""
        rows = self.query(
            """
            SELECT j.id
              FROM jobs AS j
              LEFT JOIN job_leases AS l ON l.job_id = j.id
             WHERE j.status = 'running'
               AND (l.job_id IS NULL
                    OR (julianday(?) - julianday(l.beat_at)) * 86400.0 > l.ttl_seconds)
             ORDER BY j.queue_pos, j.id
            """,
            (now_iso,),
        )
        return [str(row["id"]) for row in rows]

    def settle_orphan_job(
        self,
        job_id: str,
        *,
        now_iso: str,
        failure_reason: str,
        not_run_reason: str,
    ) -> dict[str, Any]:
        """Write the dead job and its task rows to terminal states, once.

        Three statements in one transaction: a job marked failed while its own
        rows still say ``running`` would hold a concurrency slot in every count
        the queue makes (``admit_job`` counts rows, not processes), and the
        report would show a job that finished with tasks still pending forever.
        """
        with self._lock, self._conn:
            moved = self._conn.execute(
                """
                UPDATE jobs SET status = 'failed', finished_at = ?, error = ?
                 WHERE id = ? AND status = 'running'
                """,
                (now_iso, failure_reason, job_id),
            ).rowcount == 1
            stopped = self._conn.execute(
                """
                UPDATE job_tasks SET status = 'failed', finished_at = ?, failure_reason = ?
                 WHERE job_id = ? AND status = 'running'
                """,
                (now_iso, failure_reason, job_id),
            ).rowcount
            skipped = self._conn.execute(
                """
                UPDATE job_tasks SET status = 'skipped', finished_at = ?, failure_reason = ?
                 WHERE job_id = ? AND status IN ('pending', 'queued')
                """,
                (now_iso, not_run_reason, job_id),
            ).rowcount
            self._conn.execute("DELETE FROM job_leases WHERE job_id = ?", (job_id,))
        return {
            "job_id": job_id,
            "settled": moved,
            "tasks_failed": stopped,
            "tasks_skipped": skipped,
        }

    # ── read helpers ──────────────────────────────────────────────────────────

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_dict(row) for row in rows]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        found = self.query(sql, params)
        return found[0] if found else None

    # ── jobs ──────────────────────────────────────────────────────────────────

    def insert_job(self, job: dict[str, Any]) -> None:
        sql, values = _job_insert(job)
        self.execute(sql, values)

    def insert_job_with_datasets(
        self, job: dict[str, Any], datasets: Sequence[dict[str, Any]]
    ) -> None:
        """Write one job row and its dataset snapshot in a single transaction.

        Submission needs both or neither.  Split across two commits, a process
        that dies between them leaves a ``new`` row whose snapshot is missing or
        half-written -- and the startup reconcile only settles ``running`` jobs,
        so that row is a permanent phantom in the listing that no code path can
        finish.  The snapshot is what a job's results are reproduced from, so it
        is part of the job's existence rather than a follow-up write.
        """
        sql, values = _job_insert(job)
        with self._lock, self._conn:
            self._conn.execute(sql, values)
            for row in datasets:
                self._conn.execute(*_job_dataset_insert(row))

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))

    def list_jobs(
        self,
        *,
        statuses: Sequence[str] = (),
        submitter: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs"
        clauses, params = [], []
        if statuses:
            clauses.append(f"status IN ({_placeholders(statuses)})")
            params.extend(statuses)
        if submitter:
            clauses.append("submitter = ?")
            params.append(submitter)
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY queue_pos ASC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return self.query(sql, params)

    def jobs_in_state(self, *statuses: str) -> list[dict[str, Any]]:
        return self.list_jobs(statuses=statuses)

    def job_task_totals(self, job_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Per-job aggregates for the list view: tasks, done, failed, mean score.

        One grouped query rather than one per row.  The dashboard polls this
        list, so the choice is between a single scan of an indexed column and
        N queries per poll; the list view is also where a reader decides which
        report to open, and a row without a score cannot help them decide.
        """
        ids = [str(job_id) for job_id in job_ids]
        if not ids:
            return {}
        rows = self.query(
            "SELECT job_id, COUNT(*) AS task_count, "
            "SUM(CASE WHEN status = 'finished' THEN 1 ELSE 0 END) AS tasks_finished, "
            "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS tasks_failed, "
            "AVG(score) AS score "
            f"FROM job_tasks WHERE job_id IN ({_placeholders(ids)}) GROUP BY job_id",
            ids,
        )
        return {str(row["job_id"]): row for row in rows}

    def update_job(self, job_id: str, **fields: Any) -> None:
        if not fields:
            return
        columns = _checked_update_fields(_JOB_COLUMNS, fields)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        params = [_to_stored(column, fields[column]) for column in columns]
        params.append(job_id)
        self.execute(f"UPDATE jobs SET {assignments} WHERE id = ?", params)

    def count_running(self) -> int:
        return int(self._count("SELECT COUNT(*) FROM jobs WHERE status = 'running'"))

    def count_running_for(self, submitter: str) -> int:
        return int(
            self._count(
                "SELECT COUNT(*) FROM jobs WHERE status = 'running' AND submitter = ?",
                (submitter,),
            )
        )

    def max_queue_pos(self) -> float:
        row = self.query_one("SELECT MAX(queue_pos) AS highest FROM jobs")
        return float((row or {}).get("highest") or 0.0)

    def queue_positions(self) -> list[tuple[str, float]]:
        rows = self.query("SELECT id, queue_pos FROM jobs ORDER BY queue_pos ASC, id ASC")
        return [(row["id"], float(row["queue_pos"])) for row in rows]

    def set_queue_pos(self, job_id: str, position: float) -> None:
        self.update_job(job_id, queue_pos=float(position))

    # ── job ↔ datasets ────────────────────────────────────────────────────────

    def insert_job_dataset(self, row: dict[str, Any]) -> None:
        self.execute(*_job_dataset_insert(row))

    def list_job_datasets(self, job_id: str) -> list[dict[str, Any]]:
        return self.query(
            "SELECT * FROM job_datasets WHERE job_id = ? ORDER BY dataset_id",
            (job_id,),
        )

    def dataset_job_refs(self, dataset_id: str) -> list[str]:
        rows = self.query(
            "SELECT DISTINCT job_id FROM job_datasets WHERE dataset_id = ?", (dataset_id,)
        )
        return [row["job_id"] for row in rows]

    # ── datasets ──────────────────────────────────────────────────────────────

    def upsert_dataset(self, dataset: dict[str, Any]) -> None:
        now = utc_now_iso()
        self.execute(
            "INSERT INTO datasets "
            "(id, name, owner, kind, description, categories, task_ids, filter_spec, "
            " created_at, updated_at, task_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  name = excluded.name, description = excluded.description, "
            "  categories = excluded.categories, task_ids = excluded.task_ids, "
            "  filter_spec = excluded.filter_spec, updated_at = excluded.updated_at, "
            "  task_count = excluded.task_count",
            (
                dataset["id"],
                dataset.get("name") or dataset["id"],
                dataset["owner"],
                dataset["kind"],
                dataset.get("description"),
                _to_stored("categories", dataset.get("categories", [])),
                _to_stored("task_ids", dataset.get("task_ids", [])),
                _to_stored("filter_spec", dataset.get("filter_spec")),
                dataset.get("created_at") or now,
                now,
                int(dataset.get("task_count") or len(dataset.get("task_ids") or [])),
            ),
        )

    def get_dataset(self, dataset_id: str) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM datasets WHERE id = ?", (dataset_id,))

    def list_datasets(self, *, kind: str | None = None) -> list[dict[str, Any]]:
        if kind:
            return self.query(
                "SELECT * FROM datasets WHERE kind = ? ORDER BY name COLLATE NOCASE", (kind,)
            )
        return self.query("SELECT * FROM datasets ORDER BY name COLLATE NOCASE")

    def delete_dataset(self, dataset_id: str) -> None:
        self.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))

    # ── categories ────────────────────────────────────────────────────────────

    def insert_category(self, category: dict[str, Any]) -> None:
        self.execute(
            "INSERT INTO dataset_categories (name, description, created_by, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                category["name"],
                category.get("description"),
                category.get("created_by"),
                category.get("created_at") or utc_now_iso(),
            ),
        )

    def get_category(self, name: str) -> dict[str, Any] | None:
        return self.query_one("SELECT * FROM dataset_categories WHERE name = ?", (name,))

    def list_categories(self) -> list[dict[str, Any]]:
        return self.query("SELECT * FROM dataset_categories ORDER BY name")

    def delete_category(self, name: str) -> None:
        self.execute("DELETE FROM dataset_categories WHERE name = ?", (name,))

    def category_dataset_counts(self) -> dict[str, int]:
        """How many datasets carry each category, from one pass over the catalogue.

        The dashboard's category list shows a count for *every* category, so this
        is the shape its callers want: reading and decoding the ``categories``
        column once covers all of them, while asking per name would run the same
        full-table read again for each ``dataset_categories`` row.
        """
        counts: dict[str, int] = {}
        for row in self.query("SELECT categories FROM datasets"):
            # ``dict.fromkeys`` rather than the raw list: the column is whatever
            # the caller's JSON said, so one dataset naming a category twice is
            # one membership, not two -- the count is datasets, not tags.
            for name in dict.fromkeys(row.get("categories") or []):
                counts[name] = counts.get(name, 0) + 1
        return counts

    def datasets_with_category(self, name: str) -> int:
        return self.category_dataset_counts().get(name, 0)

    # ── job tasks ─────────────────────────────────────────────────────────────

    def insert_job_tasks(self, rows: Sequence[dict[str, Any]]) -> None:
        self.executemany(
            "INSERT OR REPLACE INTO job_tasks "
            "(job_id, task_id, attempt, status, grading_type, resolved_from) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    row["job_id"],
                    row["task_id"],
                    int(row.get("attempt") or 1),
                    row.get("status") or "pending",
                    row.get("grading_type"),
                    _to_stored("resolved_from", row.get("resolved_from", [])),
                )
                for row in rows
            ],
        )

    def update_job_task(self, job_id: str, task_id: str, attempt: int, **fields: Any) -> None:
        if not fields:
            return
        columns = _checked_update_fields(_JOB_TASK_COLUMNS, fields)
        assignments = ", ".join(f"{column} = ?" for column in columns)
        params = [_to_stored(column, fields[column]) for column in columns]
        params.extend([job_id, task_id, int(attempt)])
        self.execute(
            f"UPDATE job_tasks SET {assignments} WHERE job_id = ? AND task_id = ? AND attempt = ?",
            params,
        )

    def skip_unrun_tasks(
        self, job_id: str, *, reason: str, now_iso: str, attempt: int | None = None
    ) -> int:
        """Label every task row the service never started, in one statement.

        One UPDATE rather than one per row: these rows are the difference between
        "we did not reach these" and a terminal job with ``pending`` tasks under
        it, and a half-applied version of that is exactly the reading the next
        person has to argue about.  A row already moving or already closed is
        left alone -- this names what did not happen, it does not rewrite what
        did.  The count comes back because every caller logs it.
        """
        sql = (
            "UPDATE job_tasks SET status = 'skipped', failure_reason = ?, "
            "duration_s = 0.0, finished_at = ? "
            "WHERE job_id = ? AND status = 'pending'"
        )
        params: list[Any] = [reason, now_iso, job_id]
        if attempt is not None:
            sql += " AND attempt = ?"
            params.append(int(attempt))
        with self._lock, self._conn:
            return self._conn.execute(sql, params).rowcount

    def list_job_tasks(self, job_id: str) -> list[dict[str, Any]]:
        return self.query(
            "SELECT * FROM job_tasks WHERE job_id = ? ORDER BY task_id, attempt", (job_id,)
        )

    def get_job_task(
        self, job_id: str, task_id: str, attempt: int | None = None
    ) -> dict[str, Any] | None:
        if attempt is None:
            return self.query_one(
                "SELECT * FROM job_tasks WHERE job_id = ? AND task_id = ? "
                "ORDER BY attempt DESC LIMIT 1",
                (job_id, task_id),
            )
        return self.query_one(
            "SELECT * FROM job_tasks WHERE job_id = ? AND task_id = ? AND attempt = ?",
            (job_id, task_id, int(attempt)),
        )

    # ── artifacts ─────────────────────────────────────────────────────────────

    def record_artifact(self, row: dict[str, Any]) -> None:
        self.execute(
            "INSERT OR REPLACE INTO artifacts "
            "(job_id, task_id, path, sha256, size, uploaded_at, kind) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                row["job_id"],
                row["task_id"],
                row["path"],
                row["sha256"],
                int(row["size"]),
                row.get("uploaded_at") or utc_now_iso(),
                row.get("kind") or "output",
            ),
        )

    def list_artifacts(
        self, job_id: str, task_id: str | None = None, *, kind: str | None = None
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM artifacts WHERE job_id = ?"
        params: list[Any] = [job_id]
        if task_id:
            sql += " AND task_id = ?"
            params.append(task_id)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY task_id, path"
        return self.query(sql, params)

    def delete_artifact(self, job_id: str, task_id: str, path: str) -> None:
        self.execute(
            "DELETE FROM artifacts WHERE job_id = ? AND task_id = ? AND path = ?",
            (job_id, task_id, path),
        )

    # ── internals ─────────────────────────────────────────────────────────────

    def _count(self, sql: str, params: Sequence[Any] = ()) -> int:
        row = self.query_one(sql, params)
        if not row:
            return 0
        return int(next(iter(row.values())))


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    values = dict(row)
    for column in _JSON_COLUMNS:
        if column in values:
            values[column] = json.loads(values[column]) if values[column] else _empty_for(column)
    return values


def _empty_for(column: str) -> Any:
    return None if column == "env_fingerprint" or column == "filter_spec" else []


def _to_stored(column: str, value: Any) -> Any:
    if column in _JSON_COLUMNS:
        return json.dumps(value if value is not None else _empty_for(column), ensure_ascii=False)
    return value


#: The columns a submission writes, in the order it writes them.  Distinct from
#: ``_JOB_COLUMNS``, which is the unordered *set* an update is allowed to touch.
_JOB_INSERT_COLUMNS = (
    "id",
    "submitter",
    "token_subject",
    "purpose",
    "product",
    "acp_url",
    "window_kind",
    "not_before",
    "not_after",
    "status",
    "queue_pos",
    "max_tasks",
    "concurrency",
    "env_fingerprint",
    "created_at",
)


def _job_insert(job: dict[str, Any]) -> tuple[str, list[Any]]:
    """The ``INSERT INTO jobs`` statement for *job*, without running it."""
    values = [_to_stored(column, job.get(column)) for column in _JOB_INSERT_COLUMNS]
    sql = (
        f"INSERT INTO jobs ({', '.join(_JOB_INSERT_COLUMNS)}) "
        f"VALUES ({_placeholders(values)})"
    )
    return sql, values


def _job_dataset_insert(row: dict[str, Any]) -> tuple[str, list[Any]]:
    """The ``INSERT OR REPLACE INTO job_datasets`` statement for *row*."""
    values = [
        row["job_id"],
        row["dataset_id"],
        row["dataset_kind"],
        row.get("requested_by"),
        _to_stored("resolved_task_ids", row.get("resolved_task_ids")),
    ]
    return (
        "INSERT OR REPLACE INTO job_datasets "
        "(job_id, dataset_id, dataset_kind, requested_by, resolved_task_ids) "
        "VALUES (?, ?, ?, ?, ?)",
        values,
    )


def _placeholders(values: Sequence[Any]) -> str:
    return ", ".join("?" for _ in values)
