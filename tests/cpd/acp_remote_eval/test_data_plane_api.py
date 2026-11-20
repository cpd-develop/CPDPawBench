# -*- coding: utf-8 -*-
"""The data plane as an HTTP surface: what a remote agent actually sends.

These cases go through the app, not through :class:`.Exchange` directly, because
the parts that only exist at the boundary are the ones the unit tests in
``test_exchange.py`` cannot see -- the query-string spelling of a signature, the
``Bearer`` prefix, and which refusals become which status code.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pawbench.cpd.acp_remote_eval.service.api import create_app
from pawbench.cpd.acp_remote_eval.service.attempts import AttemptRegistry, LiveAttempt
from pawbench.cpd.acp_remote_eval.service.store import Store
from support import BASE, NOW, FakeTask, dataset_root, make_exchange, one_asset_task


def _local_path(url: Any) -> str:
    """Drop the configured base so TestClient hits its own app."""
    return str(url).replace(BASE, "")


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return dataset_root(tmp_path)


@pytest.fixture()
def client(store: Store, tmp_path: Path, root: Path) -> TestClient:
    exchange = make_exchange(store, tmp_path)
    return TestClient(create_app(exchange=exchange))


@pytest.fixture()
def running(store: Store, tmp_path: Path, root: Path) -> tuple[TestClient, dict[str, Any], dict]:
    """An app with one live attempt and the manifest the agent was handed."""
    exchange = make_exchange(store, tmp_path)
    registry = AttemptRegistry()
    task = one_asset_task()
    manifest = exchange.build_manifest(
        job_id="job-1", task=task, dataset_root=root, attempt=1
    )
    registry.register("job-1", task.task_id, 1, LiveAttempt(task, root))
    app = create_app(exchange=exchange, registry=registry)
    context = {"task": task, "root": root, "exchange": exchange, "registry": registry}
    return TestClient(app), manifest, context


def _token_from(manifest: dict[str, Any]) -> str:
    header = str(manifest["upload"]["headers"]["Authorization"])
    return header.removeprefix("Bearer ").strip()


def _artifact_url(manifest: dict[str, Any], path: str) -> str:
    return str(manifest["upload"]["url"]).replace("{path}", path)


# ── fixture download ──────────────────────────────────────────────────────────


def test_presigned_link_downloads_the_fixture_byte_for_byte(running) -> None:
    client, manifest, _ = running
    url = manifest["assets"][0]["url"]

    response = client.get(_local_path(url))

    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert hashlib.sha256(response.content).hexdigest() == manifest["assets"][0]["sha256"]


def test_tampering_with_the_dest_invalidates_the_link(running) -> None:
    client, manifest, _ = running
    asset = manifest["assets"][0]
    path = _local_path(asset["url"]).split("?")[0]
    forged = path.replace("fixtures/mariage1.png", "fixtures/other.png")

    response = client.get(forged + "?" + asset["url"].split("?", 1)[1])

    assert response.status_code == 403
    assert response.json()["error"] == "asset_link_invalid"


def test_an_expired_link_is_refused(store, tmp_path, root) -> None:
    """A link stops working when its window closes, however well it is signed.

    The two exchanges share the signing key and differ only in clock, which is
    the shape of a service that kept running while an agent sat on the manifest.
    """
    task = one_asset_task()
    minted = make_exchange(store, tmp_path, asset_url_ttl_seconds=60)
    manifest = minted.build_manifest(job_id="job-1", task=task, dataset_root=root)
    registry = AttemptRegistry()
    registry.register("job-1", task.task_id, 1, LiveAttempt(task, root))
    hour_later = make_exchange(
        store,
        tmp_path,
        now=NOW + timedelta(hours=1),
        presigner=minted.presigner,
        tokens=minted.tokens,
    )
    client = TestClient(create_app(exchange=hour_later, registry=registry))

    response = client.get(_local_path(manifest["assets"][0]["url"]))

    assert response.status_code == 403
    assert response.json()["error"] == "asset_link_invalid"


def test_a_link_for_an_attempt_this_service_is_not_running_is_404(
    store, tmp_path, root
) -> None:
    exchange = make_exchange(store, tmp_path)
    task = one_asset_task()
    manifest = exchange.build_manifest(job_id="job-1", task=task, dataset_root=root)
    client = TestClient(create_app(exchange=exchange, registry=AttemptRegistry()))

    response = client.get(_local_path(manifest["assets"][0]["url"]))

    assert response.status_code == 404
    assert response.json()["error"] == "attempt_not_running"


def test_healthz_reports_the_configured_address_not_the_request_host(client) -> None:
    response = client.get("/healthz", headers={"Host": "attacker.example"})

    assert response.status_code == 200
    assert response.json()["public_base_url"] == BASE


# ── artifact upload ───────────────────────────────────────────────────────────


def test_a_run_token_takes_a_result_file(running, store) -> None:
    client, manifest, _ = running

    response = client.put(
        _artifact_url(manifest, "output/answer.md"),
        content=b"# answer\n",
        headers={"Authorization": f"Bearer {_token_from(manifest)}"},
    )

    assert response.status_code == 201, response.text
    assert response.json()["path"] == "output/answer.md"
    rows = store.list_artifacts("job-1", task_id="M006_score_mariage", kind="output")
    assert [row["path"] for row in rows] == ["output/answer.md"]


def test_uploading_without_a_token_is_refused_and_writes_nothing(running, store) -> None:
    client, manifest, _ = running

    response = client.put(_artifact_url(manifest, "output/answer.md"), content=b"x")

    assert response.status_code == 403
    assert response.json()["error"] == "run_token_invalid"
    assert store.list_artifacts("job-1", task_id="M006_score_mariage", kind="output") == []


@pytest.mark.parametrize(
    "path, code",
    [
        ("/etc/passwd", "path_absolute"),
        ("../escape.md", "path_escape"),
        (".hidden.md", "hidden_path"),
        ("conftest.py", "forbidden_name"),
        ("notes.exe", "extension_not_allowed"),
        ("", "empty_path"),
    ],
)
def test_a_refused_path_never_reaches_disk(running, path, code) -> None:
    client, manifest, context = running
    uploads = context["exchange"].uploads_dir("job-1", "M006_score_mariage", 1)

    response = client.put(
        _artifact_url(manifest, path),
        content=b"payload",
        headers={"Authorization": f"Bearer {_token_from(manifest)}"},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"] == code
    assert list(uploads.glob("*")) == []


def test_the_upload_budget_stops_after_its_count(running) -> None:
    client, manifest, _ = running
    token = _token_from(manifest)
    statuses = [
        client.put(
            _artifact_url(manifest, f"output/file{i}.md"),
            content=b"x",
            headers={"Authorization": f"Bearer {token}"},
        ).status_code
        for i in range(6)
    ]

    assert statuses == [201, 201, 201, 201, 403, 403]


def test_an_oversized_body_is_refused_before_it_is_read(running) -> None:
    client, manifest, _ = running

    response = client.put(
        _artifact_url(manifest, "output/big.md"),
        content=b"x" * 5000,
        headers={
            "Authorization": f"Bearer {_token_from(manifest)}",
            "Content-Length": "5000",
        },
    )

    assert response.status_code == 413
    assert response.json()["error"] == "artifact_too_large"


def test_a_token_is_valid_only_for_the_attempt_it_was_minted_for(running) -> None:
    client, manifest, context = running
    # The second task is really running, so the refusal below comes from the
    # token's scope and not from the route simply being closed.
    other = FakeTask(task_id="T002_other")
    context["registry"].register("job-1", other.task_id, 1, LiveAttempt(other, context["root"]))
    url = _artifact_url(manifest, "output/answer.md").replace("M006_score_mariage", other.task_id)

    response = client.put(
        url, content=b"x", headers={"Authorization": f"Bearer {_token_from(manifest)}"}
    )

    assert response.status_code == 403
    assert response.json()["error"] == "run_token_invalid"
