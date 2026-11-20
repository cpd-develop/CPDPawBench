# -*- coding: utf-8 -*-
"""The data plane: presigned fixture links, upload defenses, workspace rebuild.

Nothing here talks to an agent.  These are the checks that hold when one
finally does, and the ones an outside reviewer can only verify by reading if
they are not tested.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

from pawbench.cpd.acp_remote_eval.service.exchange import (
    Exchange,
    ExchangeError,
    Presigner,
    RunTokenVault,
)
from pawbench.cpd.acp_remote_eval.service.store import Store
from support import (
    BASE,
    NOW,
    FakeTask,
    dataset_root,
    exchange_config,
    leakage_rules,
    make_exchange,
    service_config,
)


def signed_asset_url(manifest: Mapping[str, Any], index: int = 0) -> str:
    return str(manifest["assets"][index]["url"])


# ── manifest ──────────────────────────────────────────────────────────────────


def test_manifest_lists_fixtures_with_signed_links(store: Store, tmp_path: Path) -> None:
    root = dataset_root(tmp_path)
    exchange = make_exchange(store, tmp_path)
    task = FakeTask(
        workspace_files=(
            {
                "source": "assets/T002/fixtures/mariage1.png",
                "dest": "fixtures/mariage1.png",
            },
        )
    )

    manifest = exchange.build_manifest(
        job_id="job-1", task=task, dataset_root=root
    )

    asset = manifest["assets"][0]
    assert asset["dest"] == "fixtures/mariage1.png"
    assert asset["size"] == len(b"png-bytes")
    assert asset["sha256"] == hashlib.sha256(b"png-bytes").hexdigest()
    assert asset["url"].startswith(f"{BASE}/v1/exchange/job-1/{task.task_id}/1/assets/")
    assert "sig=" in asset["url"]
    assert manifest["prompt"] == task.prompt
    assert manifest["protocol"] == "pawbench-exchange/1"


def test_a_manifest_carries_nothing_from_the_grading_side(
    store: Store, tmp_path: Path
) -> None:
    """F2: the document handed to the agent is scanned with K2's rules.

    The subject team owns the agent being measured, so a rubric in the manifest
    is an answer sheet sent to the examinee -- and it is also the one payload in
    this feature that leaves through a prompt rather than an endpoint, which is
    why no response-body assertion elsewhere would have caught it.
    """
    rules = leakage_rules()
    root = dataset_root(tmp_path)
    exchange = make_exchange(store, tmp_path)
    task = FakeTask(
        workspace_files=(
            {"source": "assets/T002/fixtures/mariage1.png", "dest": "fixtures/a.png"},
        )
    )

    manifest = exchange.build_manifest(job_id="job-1", task=task, dataset_root=root)

    assert rules.find_in_payload(manifest, rules.FORWARDABLE) == []
    # The scan is not vacuous: the same two sentences copied one field away do
    # trip it, which is the mistake this case exists to catch.
    planted = rules.find_in_payload(
        {"expected_behavior": task.expected_behavior}, rules.FORWARDABLE
    )
    assert "key expected_behavior (at expected_behavior)" in planted, planted
    assert task.expected_behavior not in json.dumps(manifest)
    assert task.llm_judge_rubric not in json.dumps(manifest)


def test_manifest_urls_only_ever_use_the_configured_base(
    store: Store, tmp_path: Path
) -> None:
    root = dataset_root(tmp_path)
    exchange = make_exchange(
        store, tmp_path, service=service_config(public_base_url="http://10.0.0.7:8471")
    )
    task = FakeTask(
        workspace_files=({"source": "assets/T002/fixtures/mariage1.png", "dest": "a.png"},)
    )

    manifest = exchange.build_manifest(job_id="job-1", task=task, dataset_root=root)

    for url in (manifest["assets"][0]["url"], manifest["upload"]["url"]):
        assert url.startswith("http://10.0.0.7:8471")
    assert "localhost" not in str(manifest)


def test_upload_grant_expires_with_the_timeout_multiplier(
    store: Store, tmp_path: Path
) -> None:
    root = dataset_root(tmp_path)
    exchange = make_exchange(store, tmp_path)
    task = FakeTask(timeout_seconds=1200)

    manifest = exchange.build_manifest(job_id="job-1", task=task, dataset_root=root)

    expiry = datetime.fromisoformat(manifest["expires_at"])
    assert expiry == NOW + timedelta(seconds=1800)
    assert manifest["upload"]["budget"] == 4


def test_short_timeout_still_gets_a_minimal_grant(
    store: Store, tmp_path: Path
) -> None:
    root = dataset_root(tmp_path)
    exchange = make_exchange(store, tmp_path)

    manifest = exchange.build_manifest(
        job_id="job-1", task=FakeTask(timeout_seconds=10), dataset_root=root
    )

    assert datetime.fromisoformat(manifest["expires_at"]) == NOW + timedelta(seconds=60)


def test_asset_links_live_shorter_than_the_run(
    store: Store, tmp_path: Path
) -> None:
    root = dataset_root(tmp_path)
    exchange = make_exchange(store, tmp_path, asset_url_ttl_seconds=300)
    task = FakeTask(
        timeout_seconds=1200,
        workspace_files=({"source": "assets/T002/fixtures/mariage1.png", "dest": "a.png"},),
    )

    manifest = exchange.build_manifest(job_id="job-1", task=task, dataset_root=root)

    asset_expiry = datetime.fromisoformat(manifest["assets"][0]["expires_at"])
    run_expiry = datetime.fromisoformat(manifest["expires_at"])
    assert asset_expiry == NOW + timedelta(seconds=300)
    assert asset_expiry < run_expiry


def test_manifest_embeds_the_bearer_token_not_its_hash(
    store: Store, tmp_path: Path
) -> None:
    exchange = make_exchange(store, tmp_path)

    manifest = exchange.build_manifest(
        job_id="job-1", task=FakeTask(), dataset_root=dataset_root(tmp_path)
    )

    token = manifest["upload"]["headers"]["Authorization"].removeprefix("Bearer ")
    assert len(token) >= 32
    assert token not in exchange.tokens._grants, "only the hash is a key"


# ── tokens ────────────────────────────────────────────────────────────────────


def test_token_authorises_only_its_own_attempt() -> None:
    vault = RunTokenVault()
    token, grant = vault.issue(
        "job-1", "task-a", 1, ttl_seconds=600, max_uploads=2, now=NOW
    )

    assert grant.job_id == "job-1"
    vault.authorize(token, "job-1", "task-a", 1, NOW)
    for args in (
        ("job-2", "task-a", 1),
        ("job-1", "task-b", 1),
        ("job-1", "task-a", 2),
    ):
        with pytest.raises(ExchangeError) as caught:
            vault.authorize(token, *args, NOW)
        assert caught.value.code == "run_token_invalid", "one answer for every mismatch"


def test_token_budget_and_expiry_are_enforced() -> None:
    vault = RunTokenVault()
    token, _ = vault.issue("job-1", "task-a", 1, ttl_seconds=600, max_uploads=2, now=NOW)

    vault.authorize(token, "job-1", "task-a", 1, NOW)
    vault.authorize(token, "job-1", "task-a", 1, NOW)

    with pytest.raises(ExchangeError) as spent:
        vault.authorize(token, "job-1", "task-a", 1, NOW)
    assert spent.value.code == "run_token_spent"

    fresh, _ = vault.issue("job-9", "task-a", 1, ttl_seconds=60, max_uploads=1, now=NOW)
    with pytest.raises(ExchangeError) as expired:
        vault.authorize(fresh, "job-9", "task-a", 1, NOW + timedelta(seconds=61))
    assert expired.value.code == "run_token_expired"


def test_a_single_upload_slot_is_not_spent_twice_by_two_threads() -> None:
    """The budget is spent inside the route, and the route runs on threads.

    Hashing, fsync and the SQLite write moved off the event loop, so two
    uploads of one attempt arrive on two threads at once.  Authorising is a
    read-then-write on one shared grant, so without a lock both threads can see
    the last slot free and the agent gets a file more than the run allows.
    """
    vault = RunTokenVault()
    token, _ = vault.issue("job-1", "task-a", 1, ttl_seconds=600, max_uploads=1, now=NOW)

    racers = 16
    barrier = threading.Barrier(racers)
    accepted: list[bool] = []

    def spend() -> None:
        barrier.wait()
        try:
            vault.authorize(token, "job-1", "task-a", 1, NOW)
        except ExchangeError:
            return
        accepted.append(True)

    threads = [threading.Thread(target=spend) for _ in range(racers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(accepted) == 1, f"{len(accepted)} uploads for one slot"


def test_a_refused_upload_does_not_cost_the_run_a_slot() -> None:
    """Budget is spent on an accepted file, not on an attempt to send one.

    Spending on arrival meant 64 PUTs with bad paths could drain the grant, and
    the agent's real results then came back ``run_token_spent``.
    """
    vault = RunTokenVault()
    token, _ = vault.issue("job-1", "task-a", 1, ttl_seconds=600, max_uploads=1, now=NOW)

    for _ in range(8):
        with pytest.raises(ExchangeError):
            vault.authorize(token, "job-1", "task-b", 1, NOW)

    vault.authorize(token, "job-1", "task-a", 1, NOW)
    with pytest.raises(ExchangeError) as spent:
        vault.authorize(token, "job-1", "task-a", 1, NOW)
    assert spent.value.code == "run_token_spent"


def test_checking_a_token_leaves_the_whole_budget_intact() -> None:
    """The route checks before it reads the body, so checking must not spend."""
    vault = RunTokenVault()
    token, _ = vault.issue("job-1", "task-a", 1, ttl_seconds=600, max_uploads=2, now=NOW)

    for _ in range(5):
        vault.check(token, "job-1", "task-a", 1, NOW)

    assert vault.status("job-1", "task-a", 1)[0].uploads_used == 0
    with pytest.raises(ExchangeError) as refused:
        vault.check("guess-me", "job-1", "task-a", 1, NOW)
    assert refused.value.code == "run_token_invalid"


def test_unknown_token_is_refused() -> None:
    vault = RunTokenVault()
    with pytest.raises(ExchangeError) as caught:
        vault.authorize("guess-me", "job-1", "task-a", 1, NOW)
    assert caught.value.code == "run_token_invalid"


def test_revoke_drops_every_grant_for_a_task() -> None:
    vault = RunTokenVault()
    first, _ = vault.issue("job-1", "task-a", 1, ttl_seconds=600, max_uploads=1, now=NOW)
    second, _ = vault.issue("job-1", "task-b", 1, ttl_seconds=600, max_uploads=1, now=NOW)

    assert vault.revoke("job-1", "task-a") == 1
    with pytest.raises(ExchangeError):
        vault.authorize(first, "job-1", "task-a", 1, NOW)
    vault.authorize(second, "job-1", "task-b", 1, NOW)


# ── presigner ─────────────────────────────────────────────────────────────────


def test_signature_covers_the_resource_and_the_expiry() -> None:
    presigner = Presigner(secret=b"test-secret")
    expires = NOW + timedelta(seconds=900)
    resource = ("asset", "job-1", "task-a", "1", "fixtures/a.png")
    signature = presigner.signature(resource, expires)

    assert presigner.verify(resource, expires, signature, NOW) is True
    assert presigner.verify(resource[:-1] + ("fixtures/b.png",), expires, signature, NOW) is False
    assert presigner.verify(("asset", "job-1", "task-b", "1", resource[4]), expires, signature, NOW) is False
    assert presigner.verify(resource, expires + timedelta(seconds=1), signature, NOW) is False
    assert presigner.verify(resource, expires, "deadbeef", NOW) is False
    assert presigner.verify(resource, expires, signature, expires) is False


def test_verify_asset_request_returns_the_dest_and_rejects_tampering(
    store: Store, tmp_path: Path
) -> None:
    root = dataset_root(tmp_path)
    exchange = make_exchange(store, tmp_path)
    task = FakeTask(
        workspace_files=({"source": "assets/T002/fixtures/mariage1.png", "dest": "fixtures/mariage1.png"},)
    )
    manifest = exchange.build_manifest(job_id="job-1", task=task, dataset_root=root)
    url = signed_asset_url(manifest)
    query = dict(
        item.split("=", 1) for item in url.split("?", 1)[1].split("&")
    )

    dest = exchange.verify_asset_request(
        job_id="job-1",
        task_id=task.task_id,
        attempt=1,
        dest="fixtures/mariage1.png",
        expires=query["expires"],
        signature=query["sig"],
    )
    assert dest == "fixtures/mariage1.png"

    with pytest.raises(ExchangeError) as caught:
        exchange.verify_asset_request(
            job_id="job-1",
            task_id=task.task_id,
            attempt=1,
            dest="assets/T002/fixtures/mariage1.png",
            expires=query["expires"],
            signature=query["sig"],
        )
    assert caught.value.code == "asset_link_invalid"

    with pytest.raises(ExchangeError) as bad_expiry:
        exchange.verify_asset_request(
            job_id="job-1",
            task_id=task.task_id,
            attempt=1,
            dest="fixtures/mariage1.png",
            expires="not-a-number",
            signature=query["sig"],
        )
    assert bad_expiry.value.code == "bad_asset_link"


def test_fixture_for_maps_a_dest_back_to_its_file(store: Store, tmp_path: Path) -> None:
    root = dataset_root(tmp_path)
    exchange = make_exchange(store, tmp_path)
    task = FakeTask(
        workspace_files=({"source": "assets/T002/fixtures/mariage1.png", "dest": "fixtures/mariage1.png"},)
    )

    path = exchange.fixture_for(task, root, "fixtures/mariage1.png")

    assert path.read_bytes() == b"png-bytes"
    with pytest.raises(ExchangeError) as caught:
        exchange.fixture_for(task, root, "fixtures/other.png")
    assert caught.value.code == "asset_unknown_dest"


# ── path defenses ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "raw_path,code",
    [
        ("", "empty_path"),
        ("\x00", "bad_path"),
        ("/etc/passwd", "path_absolute"),
        ("C:/Windows/system.ini", "path_absolute"),
        ("../outside.md", "path_escape"),
        ("reports/../../outside.md", "path_escape"),
        ("./notes.md", "path_escape"),
        ("notes.md/", "path_escape"),
        (".hidden.md", "hidden_path"),
        ("reports/.git/config", "hidden_path"),
        ("conftest.py", "forbidden_name"),
        ("tests/CONFTEST.PY", "forbidden_name"),
        ("pytest.ini", "forbidden_name"),
        ("sitecustomize.py", "forbidden_name"),
        ("my/path.pth", "forbidden_suffix"),
        ("answer.PTH", "forbidden_suffix"),
        ("answer.exe", "extension_not_allowed"),
        ("answer", "extension_not_allowed"),
        ("a/" * 20 + "b.md", "path_too_deep"),
    ],
)
def test_refused_artifact_paths(store: Store, tmp_path: Path, raw_path: str, code: str) -> None:
    exchange = make_exchange(store, tmp_path)

    with pytest.raises(ExchangeError) as caught:
        exchange.sanitize_output_path(raw_path)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "raw_path,expected",
    [
        ("answer.md", "answer.md"),
        ("reports/2026/q1.xlsx", "reports/2026/q1.xlsx"),
        ("fixtures\\mariage1.png", "fixtures/mariage1.png"),
        ("  spaced/name.txt  ", "spaced/name.txt"),
    ],
)
def test_accepted_artifact_paths(
    store: Store, tmp_path: Path, raw_path: str, expected: str
) -> None:
    exchange = make_exchange(store, tmp_path)
    assert exchange.sanitize_output_path(raw_path) == expected


def test_declared_prefixes_narrow_where_artifacts_may_land(
    store: Store, tmp_path: Path
) -> None:
    exchange = make_exchange(store, tmp_path, allowed_output_prefixes=("output", "reports"))

    assert exchange.sanitize_output_path("output/a.xlsx") == "output/a.xlsx"
    assert exchange.sanitize_output_path("output/nested/b.md") == "output/nested/b.md"
    assert exchange.sanitize_output_path("reports/q1/b.md") == "reports/q1/b.md"
    for rejected in ("answer.md", "outputsneaky/a.md", "output.md"):
        with pytest.raises(ExchangeError) as caught:
            exchange.sanitize_output_path(rejected)
        assert caught.value.code == "prefix_not_allowed"


# ── ingest ────────────────────────────────────────────────────────────────────


def manifest_for(store: Store, tmp_path: Path, **kwargs: Any) -> tuple[Exchange, dict, FakeTask]:
    exchange = make_exchange(store, tmp_path, **kwargs)
    root = dataset_root(tmp_path)
    task = FakeTask(
        workspace_files=({"source": "assets/T002/fixtures/mariage1.png", "dest": "fixtures/mariage1.png"},)
    )
    return exchange, exchange.build_manifest(
        job_id="job-1", task=task, dataset_root=root
    ), task


def token_of(manifest: Mapping[str, Any]) -> str:
    return str(manifest["upload"]["headers"]["Authorization"].removeprefix("Bearer "))


def test_accepted_artifact_lands_in_uploads_and_records(
    store: Store, tmp_path: Path
) -> None:
    exchange, manifest, task = manifest_for(store, tmp_path)

    upload = exchange.accept_artifact(
        job_id="job-1",
        task_id=task.task_id,
        attempt=1,
        token=token_of(manifest),
        raw_path="answer.md",
        data=b"# result\n",
    )

    rows = store.list_artifacts("job-1", task_id=task.task_id)
    assert upload.path == "answer.md"
    assert upload.sha256 == hashlib.sha256(b"# result\n").hexdigest()
    assert upload.stored_at.read_bytes() == b"# result\n"
    assert [row["kind"] for row in rows] == ["output"]
    assert not list(exchange.quarantine_dir("job-1", task.task_id, 1).glob("*.part"))


def test_upload_budget_stops_a_flooding_agent(store: Store, tmp_path: Path) -> None:
    exchange, manifest, task = manifest_for(store, tmp_path, max_uploads_per_run=2)
    token = token_of(manifest)

    for index in range(2):
        exchange.accept_artifact(
            job_id="job-1",
            task_id=task.task_id,
            attempt=1,
            token=token,
            raw_path=f"a{index}.md",
            data=b"x",
        )

    with pytest.raises(ExchangeError) as caught:
        exchange.accept_artifact(
            job_id="job-1",
            task_id=task.task_id,
            attempt=1,
            token=token,
            raw_path="a2.md",
            data=b"x",
        )
    assert caught.value.code == "run_token_spent"
    assert len(store.list_artifacts("job-1", task_id=task.task_id)) == 2


def test_oversized_artifact_is_refused_before_it_is_written(
    store: Store, tmp_path: Path
) -> None:
    exchange, manifest, task = manifest_for(store, tmp_path, max_bytes_per_artifact=8)

    with pytest.raises(ExchangeError) as caught:
        exchange.accept_artifact(
            job_id="job-1",
            task_id=task.task_id,
            attempt=1,
            token=token_of(manifest),
            raw_path="big.md",
            data=b"y" * 64,
        )

    assert caught.value.code == "artifact_too_large"
    assert store.list_artifacts("job-1", task_id=task.task_id) == []
    assert not list(exchange.quarantine_dir("job-1", task.task_id, 1).glob("*.part"))


def test_refused_names_never_reach_disk(store: Store, tmp_path: Path) -> None:
    exchange, manifest, task = manifest_for(store, tmp_path)
    token = token_of(manifest)

    for path in ("conftest.py", "../escape.md", ".hidden.md"):
        with pytest.raises(ExchangeError):
            exchange.accept_artifact(
                job_id="job-1",
                task_id=task.task_id,
                attempt=1,
                token=token,
                raw_path=path,
                data=b"x",
            )

    assert store.list_artifacts("job-1", task_id=task.task_id) == []
    assert not any(exchange.uploads_dir("job-1", task.task_id, 1).iterdir())


def test_upload_for_another_task_is_refused(store: Store, tmp_path: Path) -> None:
    exchange, manifest, task = manifest_for(store, tmp_path)

    with pytest.raises(ExchangeError) as caught:
        exchange.accept_artifact(
            job_id="job-1",
            task_id="some-other-task",
            attempt=1,
            token=token_of(manifest),
            raw_path="answer.md",
            data=b"x",
        )
    assert caught.value.code == "run_token_invalid"


# ── fixture source resolution ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "source,code",
    [
        ("", "bad_asset_source"),
        ("/etc/passwd", "bad_asset_source"),
        ("assets/../secrets.md", "bad_asset_source"),
        ("assets/T002/fixtures/mariage1.png/../../x.png", "bad_asset_source"),
        ("assets/T002/missing.png", "asset_not_found"),
    ],
)
def test_bad_asset_sources(store: Store, tmp_path: Path, source: str, code: str) -> None:
    exchange = make_exchange(store, tmp_path)
    with pytest.raises(ExchangeError) as caught:
        exchange.fixture_source(dataset_root(tmp_path), source)
    assert caught.value.code == code


def test_symlinked_asset_source_cannot_reach_outside_the_dataset(
    store: Store, tmp_path: Path
) -> None:
    root = dataset_root(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("secret")
    link = root / "assets" / "T002" / "fixtures" / "link.md"
    link.symlink_to(outside)
    exchange = make_exchange(store, tmp_path)

    with pytest.raises(ExchangeError) as caught:
        exchange.fixture_source(root, "assets/T002/fixtures/link.md")
    assert caught.value.code == "bad_asset_source"


# ── rebuild ───────────────────────────────────────────────────────────────────


def test_rebuild_lays_fixtures_then_uploads(store: Store, tmp_path: Path) -> None:
    exchange, manifest, task = manifest_for(store, tmp_path)
    token = token_of(manifest)

    exchange.accept_artifact(
        job_id="job-1",
        task_id=task.task_id,
        attempt=1,
        token=token,
        raw_path="output/chart.png",
        data=b"chart",
    )
    exchange.accept_artifact(
        job_id="job-1",
        task_id=task.task_id,
        attempt=1,
        token=token,
        raw_path="fixtures/mariage1.png",
        data=b"edited-by-agent",
    )

    rebuild = exchange.rebuild_workspace(
        job_id="job-1",
        task=task,
        dataset_root=dataset_root(tmp_path),
        target=tmp_path / "workspaces" / "job-1" / task.task_id,
    )

    workspace = rebuild.workspace
    assert (workspace / "output" / "chart.png").read_bytes() == b"chart"
    assert (workspace / "fixtures" / "mariage1.png").read_bytes() == b"edited-by-agent"
    assert rebuild.fixtures_laid == 1
    assert rebuild.artifacts_laid == 2
    assert rebuild.artifact_paths == ("fixtures/mariage1.png", "output/chart.png")


def test_rebuild_drops_a_previous_workspace_and_never_follows_symlinks(
    store: Store, tmp_path: Path
) -> None:
    exchange, manifest, task = manifest_for(store, tmp_path)
    token = token_of(manifest)
    exchange.accept_artifact(
        job_id="job-1",
        task_id=task.task_id,
        attempt=1,
        token=token,
        raw_path="answer.md",
        data=b"first",
    )
    target = tmp_path / "ws"
    target.mkdir()
    (target / "stale.md").write_text("stale")

    exchange.rebuild_workspace(
        job_id="job-1", task=task, dataset_root=dataset_root(tmp_path), target=target
    )
    assert not (target / "stale.md").exists()

    secret = tmp_path / "secret.txt"
    secret.write_text("do not read")
    evil = exchange.upload_path("job-1", task.task_id, 1, "answer.md")
    evil.unlink()
    evil.symlink_to(secret)

    with pytest.raises(ExchangeError) as caught:
        exchange.rebuild_workspace(
            job_id="job-1", task=task, dataset_root=dataset_root(tmp_path), target=target
        )
    assert caught.value.code == "symlink_refused"


def test_a_recorded_artifact_that_is_missing_fails_the_rebuild(
    store: Store, tmp_path: Path
) -> None:
    """A workspace that lost an answer is not an agent that gave a short one.

    Warning and returning let ``classify`` call the attempt ``finished``, so the
    grader scored an empty file as the agent's work.
    """
    exchange, manifest, task = manifest_for(store, tmp_path)
    exchange.accept_artifact(
        job_id="job-1",
        task_id=task.task_id,
        attempt=1,
        token=token_of(manifest),
        raw_path="answer.md",
        data=b"payload",
    )
    exchange.drop_attempt("job-1", task.task_id, 1)

    with pytest.raises(ExchangeError) as caught:
        exchange.rebuild_workspace(
            job_id="job-1", task=task, dataset_root=dataset_root(tmp_path), target=tmp_path / "ws"
        )

    assert caught.value.code == "artifact_missing"
    assert "answer.md" in caught.value.message


def test_attempt_paths_reject_unsafe_identifiers(store: Store, tmp_path: Path) -> None:
    exchange = make_exchange(store, tmp_path)

    with pytest.raises(ExchangeError) as caught:
        exchange.attempt_dir("../../etc", "task", 1)
    assert caught.value.code == "bad_identifier"

    with pytest.raises(ExchangeError) as caught:
        exchange.attempt_dir("job-1", "task/../x", 1)
    assert caught.value.code == "bad_identifier"
