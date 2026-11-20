# -*- coding: utf-8 -*-
"""Builders shared by the data-plane, harness and runner cases.

Kept out of ``conftest.py`` so a case can import them by name: the exchange
tests want a config with one override, which reads better as a call than as a
fixture with seven parameters.
"""

from __future__ import annotations

import importlib.util
import io
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

import httpx
from pawbench.cpd.acp_remote_eval.service.auth import StaticConfigVerifier
from pawbench.cpd.acp_remote_eval.service.config import (
    SCORE_HIJACK_FILENAMES,
    SCORE_HIJACK_SUFFIXES,
    EvalConfig,
    ExchangeConfig,
    ServiceConfig,
    parse_config,
)
from pawbench.cpd.acp_remote_eval.service.datasets import BuiltinCatalog, DatasetService
from pawbench.cpd.acp_remote_eval.service.exchange import Exchange
from pawbench.cpd.acp_remote_eval.service.schedule import FrozenClock

if TYPE_CHECKING:  # only the annotations of ``build_control_app`` need these
    from pawbench.cpd.acp_remote_eval.service.queue import JobQueue
    from pawbench.cpd.acp_remote_eval.service.store import Store

BASE = "http://127.0.0.1:8471"
NOW = datetime(2026, 11, 10, 2, 0, tzinfo=timezone.utc)


@dataclass(frozen=True)
class FakeTask:
    """The attributes the data plane reads off a task.

    It carries the grading-side fields the real task object has, even though
    nothing here reads them: a manifest built from a task that has no rubric
    cannot prove the builder leaves the rubric out.
    """

    task_id: str = "M006_score_mariage"
    prompt: str = "Reproduce the score as MIDI."
    timeout_seconds: int = 1200
    grading_type: str = "llm_judge"
    workspace_files: Sequence[Mapping[str, str]] = ()
    expected_behavior: str = "A .mid file is written under output/."
    llm_judge_rubric: str = "Award 1.0 when the file parses as SMF type 1."
    automated_checks: Sequence[Mapping[str, str]] = ()


def service_config(**overrides: Any) -> ServiceConfig:
    values: dict[str, Any] = {
        "bind": "127.0.0.1:8471",
        "public_base_url": BASE,
        "state_db": Path("state.db"),
        "max_concurrent_jobs": 4,
        "max_running_per_user": 1,
        "artifact_max_bytes_per_task": 268_435_456,
        "exchange_ttl_multiplier": 1.5,
        "max_job_seconds": 7200,
        "lease_ttl_seconds": 90.0,
    }
    values.update(overrides)
    return ServiceConfig(**values)


def exchange_config(tmp_path: Path, **overrides: Any) -> ExchangeConfig:
    values: dict[str, Any] = {
        "exchange_dir": tmp_path / "exchange",
        "asset_url_ttl_seconds": 900,
        "max_uploads_per_run": 4,
        "max_bytes_per_artifact": 4096,
        "allowed_extensions": frozenset({"xlsx", "csv", "md", "txt", "png", "py", "html"}),
        "allowed_output_prefixes": ("",),
        "forbidden_names": SCORE_HIJACK_FILENAMES,
        "forbidden_suffixes": SCORE_HIJACK_SUFFIXES,
    }
    values.update(overrides)
    return ExchangeConfig(**values)


def dataset_root(tmp_path: Path) -> Path:
    """A dataset root with one task's fixture under ``assets/``."""
    root = tmp_path / "dataset"
    fixture = root / "assets" / "T002" / "fixtures"
    fixture.mkdir(parents=True, exist_ok=True)
    (fixture / "mariage1.png").write_bytes(b"png-bytes")
    (root / "tasks").mkdir(parents=True, exist_ok=True)
    return root


def make_exchange(
    store: Any,
    tmp_path: Path,
    *,
    now: datetime = NOW,
    service: ServiceConfig | None = None,
    presigner: Any = None,
    tokens: Any = None,
    **exchange_overrides: Any,
) -> Exchange:
    return Exchange(
        store,
        service or service_config(),
        exchange_config(tmp_path, **exchange_overrides),
        clock=FrozenClock(now),
        presigner=presigner,
        tokens=tokens,
    )


def one_asset_task() -> FakeTask:
    return FakeTask(
        workspace_files=(
            {"source": "assets/T002/fixtures/mariage1.png", "dest": "fixtures/mariage1.png"},
        )
    )


def write_task(
    root: Path,
    task_id: str,
    *,
    scenario: str = "Office_Productivity/Email",
    capability: str | list[str] = "Tool_Use",
    complexity: str = "L1",
    environment: str = "closed",
    modality: str = "text",
    grading_type: str = "automated",
    timeout: int = 300,
    fixtures: tuple[str, ...] = (),
    prompt: str | None = "Write output/result.txt with the answer.",
    rubric: str | None = None,
    source: str | None = None,
    subcategory: str | None = None,
    channels: tuple[str, ...] = (),
) -> Path:
    capabilities = [capability] if isinstance(capability, str) else list(capability)
    workspace_lines = [
        f"- source: fixtures/{name}\n  dest: fixtures/{name}" for name in fixtures
    ]
    lines = [
        "---",
        f"id: {task_id}",
        f"name: task {task_id}",
        "category: office",
        f"grading_type: {grading_type}",
        f"timeout_seconds: {timeout}",
        "workspace_files:",
        *workspace_lines,
        "labels:",
        "  capabilities:",
        *[f"  - {item}" for item in capabilities],
        f"  scenario: {scenario}",
        f"  complexity: {complexity}",
        f"  environment: {environment}",
        "  modality:",
        f"    type: {modality}",
    ]
    if subcategory:
        lines.insert(4, f"subcategory: {subcategory}")
    if channels:
        lines += ["    channels:", *[f"    - {item}" for item in channels]]
    if source:
        lines.append(f"origin_benchmark: {source}")
    lines += ["---", "", "## Prompt", ""]
    if prompt is not None:
        lines += [prompt, ""]
    lines += ["## Expected Behavior", "", "A file is written."]
    if rubric is not None:
        lines += ["", "## LLM Judge Rubric", "", rubric]

    path = root / "tasks" / f"{task_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for name in fixtures:
        fixture = root / "fixtures" / name
        fixture.parent.mkdir(parents=True, exist_ok=True)
        fixture.write_text(f"content of {name}", encoding="utf-8")
    return path


def eval_config(
    workdir: Path,
    *,
    builtin_root: Path,
    public_base_url: str = BASE,
    service_overrides: Mapping[str, Any] | None = None,
    exchange_overrides: Mapping[str, Any] | None = None,
) -> EvalConfig:
    """A whole service config inside one scratch directory.

    Built through ``parse_config`` rather than by hand so a runner test reads the
    same defaults the deployed service reads.
    """
    raw: dict[str, Any] = {
        "service": {"public_base_url": public_base_url},
        "datasets": {"builtin_dir": str(builtin_root)},
        "exchange": {"exchange_dir": "exchange"},
    }
    raw["service"].update(service_overrides or {})
    raw["exchange"].update(exchange_overrides or {})
    return parse_config(raw, Path(workdir).resolve())


def dataset_service(store: Any, config: EvalConfig) -> DatasetService:
    """The catalogue over the builtin directory *config* points at."""
    return DatasetService(store, config.datasets, BuiltinCatalog(config.datasets.builtin_dir))


def build_control_app(
    *,
    store: Store,
    config: EvalConfig,
    queue: JobQueue,
    datasets: DatasetService,
    allowlist: Path,
    tmp_path: Path,
    clock: FrozenClock | None = None,
    now: datetime = NOW,
    stopped: list[str] | None = None,
    verifier: StaticConfigVerifier | None = None,
    jobs: Any = None,
) -> Any:
    """An app carrying both planes, wired the way ``daemon.build_service`` wires it.

    Every control-plane case -- jobs, datasets, reports -- needs the same
    handful of objects over one store and one exchange, and a second wiring in a
    test file is how an API test ends up passing against an app the service does
    not build.  ``stopped`` records the cancels the app forwarded, which is the
    only way a test can see the agent-facing half of a cancellation.
    """
    from pawbench.cpd.acp_remote_eval.service.api import ControlPlane, create_app
    from pawbench.cpd.acp_remote_eval.service.attempts import AttemptRegistry
    from pawbench.cpd.acp_remote_eval.service.jobs import JobService
    from pawbench.cpd.acp_remote_eval.service.reports import Reports

    frozen = clock if clock is not None else FrozenClock(now)
    seen = stopped if stopped is not None else []

    def stop_running(job_id: str) -> bool:
        seen.append(job_id)
        return True

    service = jobs or JobService(
        store=store, queue=queue, datasets=datasets, config=config, clock=frozen
    )
    exchange = make_exchange(store, tmp_path, now=now)
    control = ControlPlane(
        jobs=service,
        datasets=datasets,
        verifier=verifier or StaticConfigVerifier.from_file(allowlist),
        reports=Reports(store, exchange, datasets, clock=frozen),
        stop_running=stop_running,
    )
    return create_app(exchange=exchange, registry=AttemptRegistry(), control=control)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def cli_transport(client: Any, seen: list[httpx.Request] | None = None) -> httpx.BaseTransport:
    """A sync httpx transport that answers from *client*, a Starlette ``TestClient``.

    :class:`.cli.EvalClient` is a real httpx client, so the CLI cases have to give
    it a real transport rather than a stubbed double.  Routing, the bearer check
    and the code-to-status table stay the service's own: a CLI test that passes
    through here cannot be passing against a request shape the API stopped
    accepting.  *seen* collects each request, for the cases that have to prove
    where the token went.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        answered = client.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.content,
        )
        return httpx.Response(
            answered.status_code,
            headers=dict(answered.headers),
            content=answered.content,
        )

    return httpx.MockTransport(handler)


def zip_package(source_dir: Path, *, root: str = "") -> bytes:
    """The bytes of *source_dir* as a zip, optionally nested under one folder.

    ``root`` matters: an archive made by "compress" on a folder carries that
    folder as a single top-level entry, and unpacking has to see the same layout
    a directory copy hands over.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
            name = str(path.relative_to(source_dir))
            archive.write(path, f"{root}/{name}" if root else name)
    return buffer.getvalue()


def job_row(job_id: str, **overrides: Any) -> dict[str, Any]:
    """A ``jobs`` row the schema accepts, for tests that never read most of it.

    Every NOT NULL column is spelled out because the table checks them, and a
    missing one fails as an ``IntegrityError`` from sqlite instead of as a
    wrong assertion.  ``acp_url`` is empty on purpose: the endpoint these runs
    use is handed to the runner directly, and the cases that exercise the submit
    path write a real one through :meth:`Store.insert_job_with_datasets`.
    """
    values: dict[str, Any] = {
        "id": job_id,
        "submitter": "dev-1",
        "token_subject": "dev-1",
        "acp_url": "",
        "window_kind": "now",
        "status": "running",
        "queue_pos": 1.0,
        "created_at": NOW.isoformat(),
    }
    values.update(overrides)
    return values


@cache
def leakage_rules() -> Any:
    """The K2/F2 vocabulary, read out of ``tools/scan_shared_leakage.py``.

    ``tools/`` is a directory of scripts and not a package -- the fake ACP agent
    in it is run as a subprocess -- so the file is imported by path.  The
    alternative is a second copy of the field list inside ``test_reports.py``,
    and a copy is exactly how the two checks start disagreeing: the one that
    still passes would no longer mean the other is safe.
    """
    path = Path(__file__).resolve().parent / "tools" / "scan_shared_leakage.py"
    spec = importlib.util.spec_from_file_location("scan_shared_leakage", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the leakage vocabulary from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
