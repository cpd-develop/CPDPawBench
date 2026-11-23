# -*- coding: utf-8 -*-
"""The dataset catalogue as an HTTP surface.

``test_datasets.py`` covers the rules -- normalisation, owner checks, snapshot
semantics, package validation -- against the service.  What only shows up here
is the boundary: which refusal becomes which status, whether the catalogue
leaks a task body on the way to listing it, that an uploaded archive is unpacked
into a directory nobody can reach afterwards, and that a mixed selection built
through the API resolves the same tasks the service would resolve.

Those matter because this is the surface the dashboard and the MCP tools are
built on (design section 4).  A rule that lives in only one of the three
implementations is a rule the next person will re-litigate.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from pawbench.cpd.acp_remote_eval.service import api as api_module
from pawbench.cpd.acp_remote_eval.service import datasets as dataset_module
from pawbench.cpd.acp_remote_eval.service.auth import SCOPE_ADMIN, SCOPE_SUBMIT, add_subject
from pawbench.cpd.acp_remote_eval.service.config import EvalConfig
from pawbench.cpd.acp_remote_eval.service.datasets import DatasetService
from pawbench.cpd.acp_remote_eval.service.queue import JobQueue, QueueLimits
from pawbench.cpd.acp_remote_eval.service.schedule import FrozenClock
from pawbench.cpd.acp_remote_eval.service.store import Store

from support import (
    auth_headers,
    build_control_app,
    dataset_service,
    eval_config,
    write_task,
    zip_package,
)

ACP_URL = "http://127.0.0.1:9000/rpc"

#: The prompt sentence ``support.write_task`` puts in every task file.  The
#: *listing* must never carry it: a listing that quotes the question tells the
#: subject what is expected before it has answered anything.  One route is the
#: deliberate exception -- ``/v1/datasets/{id}/tasks/{task_id}``, where a reader
#: has asked for one task by name -- so the assertions below are about the
#: listing and the detail never drifting into each other.
PROMPT_MARK = "Write output/result.txt"


@pytest.fixture()
def builtin_root(tmp_path: Path) -> Path:
    root = tmp_path / "builtin"
    write_task(root, "mail_l1", scenario="Office_Productivity/Email")
    write_task(root, "mail_l3", scenario="Office_Productivity/Email", complexity="L3")
    write_task(root, "chart_open", scenario="Data_Analytics", environment="open")
    return root


@pytest.fixture()
def config(tmp_path: Path, builtin_root: Path) -> EvalConfig:
    return eval_config(tmp_path, builtin_root=builtin_root)


@pytest.fixture()
def clock() -> FrozenClock:
    return FrozenClock(datetime(2026, 11, 10, 9, 0, tzinfo=timezone.utc))


@pytest.fixture()
def allowlist(tmp_path: Path) -> Path:
    return tmp_path / "allowlist.yaml"


@pytest.fixture()
def tokens(allowlist: Path) -> dict[str, str]:
    return {
        "dev-1": add_subject(allowlist, "dev-1"),
        "dev-2": add_subject(allowlist, "dev-2"),
        "ops": add_subject(allowlist, "ops", scopes=[SCOPE_SUBMIT, SCOPE_ADMIN]),
    }


@pytest.fixture()
def datasets(store: Store, config: EvalConfig) -> DatasetService:
    service = dataset_service(store, config)
    service.create_builtin_view(
        dataset_id="mail",
        name="Email tasks",
        owner="dev-1",
        filter_spec={"scenario": "Office_Productivity/Email"},
        categories=["email"],
    )
    return service


@pytest.fixture()
def queue(store: Store, config: EvalConfig, clock: FrozenClock) -> JobQueue:
    return JobQueue(
        store,
        config.schedule,
        QueueLimits(
            max_concurrent_jobs=config.service.max_concurrent_jobs,
            max_running_per_user=config.service.max_running_per_user,
        ),
        clock=clock,
    )


@pytest.fixture()
def client(
    store: Store,
    config: EvalConfig,
    clock: FrozenClock,
    queue: JobQueue,
    datasets: DatasetService,
    allowlist: Path,
    tmp_path: Path,
) -> TestClient:
    return TestClient(
        build_control_app(
            store=store,
            config=config,
            queue=queue,
            datasets=datasets,
            allowlist=allowlist,
            tmp_path=tmp_path,
            clock=clock,
        )
    )


def as_(tokens: dict[str, str], subject: str = "dev-1") -> dict[str, str]:
    return auth_headers(tokens[subject])


def package_bytes(tmp_path: Path, *task_ids: str, root: str = "") -> bytes:
    source = tmp_path / "source"
    for task_id in task_ids:
        write_task(source, task_id, scenario="Custom/One")
    return zip_package(source, root=root)


def _recompress(archive: bytes, method: int = 99) -> bytes:
    """Relabel every entry of a real archive as packed with *method*.

    ``zipfile`` refuses to write a method it cannot read, so an archive from some
    other tool has to be forged by hand: the field is two bytes at offset 8 of a
    local header and offset 10 of the matching central-directory record, and both
    have to move or the reader complains about a mismatch instead of the method.
    """
    data = bytearray(archive)
    for signature, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
        start = 0
        while True:
            index = data.find(signature, start)
            if index < 0:
                break
            data[index + offset : index + offset + 2] = method.to_bytes(2, "little")
            start = index + 1
    return bytes(data)


# ── reading ───────────────────────────────────────────────────────────────────


def test_the_catalogue_lists_without_quoting_a_task(client, tokens):
    response = client.get("/v1/datasets", headers=as_(tokens))

    assert response.status_code == 200, response.text
    body = response.json()
    entry = next(item for item in body["datasets"] if item["id"] == "mail")
    assert entry == {
        "id": "mail",
        "name": "Email tasks",
        "owner": "dev-1",
        "kind": "builtin_view",
        "description": "",
        "categories": ["email"],
        "task_count": 2,
        "updated_at": entry["updated_at"],
    }
    assert body["categories"][0]["name"] == "email"
    assert body["label_distribution"]["scenario"]["Office_Productivity/Email"] == 2
    # One assertion worth its salt: the listing says a task exists, never what
    # it asks for.
    assert PROMPT_MARK not in response.text


def test_describing_a_dataset_names_tasks_without_bodies(client, tokens):
    detail = client.get("/v1/datasets/mail", headers=as_(tokens)).json()

    assert sorted(task["task_id"] for task in detail["tasks"]) == ["mail_l1", "mail_l3"]
    assert detail["filter_spec"] == {"scenario": "Office_Productivity/Email"}
    assert PROMPT_MARK not in client.get("/v1/datasets/mail", headers=as_(tokens)).text


def test_a_dataset_the_service_does_not_know_answers_404(client, tokens):
    response = client.get("/v1/datasets/nope", headers=as_(tokens))

    assert response.status_code == 404
    assert response.json()["error"] == "dataset_not_found"


# ── saving a view ─────────────────────────────────────────────────────────────


def test_saving_a_view_snapshots_the_filter_it_came_from(client, tokens):
    response = client.post(
        "/v1/datasets",
        json={
            "id": "open-set",
            "name": "Open web",
            "filter": {"environment": "open"},
            "categories": ["research"],
        },
        headers=as_(tokens),
    )

    assert response.status_code == 201, response.text
    record = response.json()
    assert record["task_ids"] == ["chart_open"]
    assert record["owner"] == "dev-1"
    assert record["categories"] == ["research"], "the category was created by the way"


def test_a_view_without_a_filter_is_refused_not_read_as_everything(client, tokens):
    response = client.post("/v1/datasets", json={"id": "oops"}, headers=as_(tokens))

    assert response.status_code == 400
    assert response.json()["error"] == "field_type_invalid"


def test_a_view_needs_an_id_of_its_own(client, tokens):
    response = client.post(
        "/v1/datasets", json={"filter": {"environment": "open"}}, headers=as_(tokens)
    )

    assert response.status_code == 400
    assert response.json()["error"] == "field_missing"


def test_recutting_moves_the_snapshot_and_keeps_the_filing(client, tokens, datasets):
    response = client.put(
        "/v1/datasets/mail",
        json={"filter": {"task_ids": ["mail_l1"]}},
        headers=as_(tokens),
    )

    assert response.status_code == 200, response.text
    record = response.json()
    assert record["task_ids"] == ["mail_l1"]
    assert record["categories"] == ["email"], "no 'categories' key means leave them"
    assert record["name"] == "Email tasks"


def test_recutting_someone_elses_view_is_refused(client, tokens):
    response = client.put(
        "/v1/datasets/mail",
        json={"filter": {"task_ids": ["chart_open"]}},
        headers=as_(tokens, "dev-2"),
    )

    assert response.status_code == 403
    assert response.json()["error"] == "not_dataset_owner"


def test_an_admin_may_recut_it(client, tokens):
    response = client.put(
        "/v1/datasets/mail",
        json={"filter": {"task_ids": ["chart_open"]}},
        headers=as_(tokens, "ops"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["task_ids"] == ["chart_open"]


def test_reuploading_is_how_a_custom_set_changes(client, tokens, tmp_path):
    client.post(
        "/v1/datasets/packages?id=cust-1&name=Cust",
        content=package_bytes(tmp_path, "cust_a"),
        headers=as_(tokens),
    )

    response = client.put(
        "/v1/datasets/cust-1",
        json={"filter": {"task_ids": ["cust_a"]}},
        headers=as_(tokens),
    )

    assert response.status_code == 400
    assert response.json()["error"] == "dataset_kind_fixed"
    assert "/v1/datasets/packages" in response.json()["message"]


# ── uploading a package ───────────────────────────────────────────────────────


def test_an_uploaded_package_becomes_a_selectable_dataset(client, tokens, tmp_path):
    response = client.post(
        "/v1/datasets/packages?id=cust-1&name=My%20set&categories=custom",
        content=package_bytes(tmp_path, "cust_a", "cust_b", root="my-set"),
        headers=as_(tokens),
    )

    assert response.status_code == 201, response.text
    record = response.json()
    assert sorted(record["task_ids"]) == ["cust_a", "cust_b"]
    assert record["kind"] == "custom"
    assert record["categories"] == ["custom"]

    preview = client.post(
        "/v1/datasets/resolve", json={"selector": {"datasets": ["cust-1"]}}, headers=as_(tokens)
    )
    assert preview.json()["task_ids"] == ["cust_a", "cust_b"]


def test_the_unpack_reaches_the_service_the_same_way_a_copy_does(
    client, tokens, tmp_path, config
):
    """The single-root folder is dropped, so ``tasks/`` sits where it is read.

    Zipping a folder -- what every file manager produces -- puts every path
    under that folder.  Unpacked literally, ``validate_package`` would find no
    markdown at all and refuse a package that is correct.
    """
    archive = package_bytes(tmp_path, "cust_a", root="my-set")

    client.post(
        "/v1/datasets/packages?id=cust-2",
        content=archive,
        headers=as_(tokens),
    )

    unpacked = Path(config.datasets.custom_dir) / "cust-2"
    assert (unpacked / "tasks" / "cust_a.md").is_file()


def test_a_package_that_fails_validation_is_refused_item_by_item(client, tokens, tmp_path):
    source = tmp_path / "source"
    write_task(source, "good_one")
    broken = source / "tasks" / "broken.md"
    broken.write_text("---\nid: broken_one\n---\n\nno prompt section\n", encoding="utf-8")

    response = client.post(
        "/v1/datasets/packages?id=bad-1",
        content=zip_package(source),
        headers=as_(tokens),
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "package_invalid"
    assert any(item["file"].endswith("broken.md") for item in payload["details"]["items"])


def test_a_refused_package_leaves_nothing_registered_or_unpacked(
    client, tokens, tmp_path, config
):
    source = tmp_path / "source"
    write_task(source, "good_one")
    (source / "tasks" / "conftest.py").write_text("import os\n", encoding="utf-8")

    response = client.post(
        "/v1/datasets/packages?id=ghost",
        content=zip_package(source),
        headers=as_(tokens),
    )

    assert response.status_code == 422, response.text
    assert client.get("/v1/datasets/ghost", headers=as_(tokens)).status_code == 404
    assert not (Path(config.datasets.custom_dir) / "ghost").exists()


@pytest.mark.parametrize(
    "member_name",
    ["../escape.md", "/absolute.md", "tasks/../../escape.md"],
)
def test_a_member_that_walks_out_of_the_package_is_refused(
    client, tokens, tmp_path, member_name
):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member_name, b"content")

    response = client.post(
        "/v1/datasets/packages?id=slip", content=buffer.getvalue(), headers=as_(tokens)
    )

    assert response.status_code == 400
    assert response.json()["error"] == "package_unsafe_path"
    assert not (tmp_path / "escape.md").exists()


def test_a_package_guard_refusal_says_who_sent_what(client, tokens, caplog):
    """The 400 tells the caller; the log has to tell us whom to look at.

    A member name that escapes the package directory probes the one place this
    service writes caller-supplied bytes to disk, and the route deletes the upload
    on its way out -- so once the unpacker has raised, the subject, the id and the
    member are all that is left of the attempt.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../escape.md", b"content")

    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/v1/datasets/packages?id=slip",
            content=buffer.getvalue(),
            headers=as_(tokens, "dev-2"),
        )

    assert response.status_code == 400
    told = [r for r in caplog.records if getattr(r, "code", "") == "package_unsafe_path"]
    assert [(r.subject, r.dataset_id, r.levelno) for r in told] == [
        ("dev-2", "slip", logging.WARNING)
    ]
    assert "escape.md" in told[0].reason


def test_a_guard_reason_is_one_line_however_the_entry_is_named(client, tokens, caplog):
    """A member name is the caller's text; a log line is not where it gets pasted.

    ``zipfile`` takes both a newline and a 4 KB name, so an unescaped reason would
    either forge a second record in whatever reads the file or push the two fields
    that identify the attempt off the line it is supposed to be readable on.
    """
    member = "../break\n" + ("n" * 4096) + "second line.md"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(member, b"content")

    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/v1/datasets/packages?id=long", content=buffer.getvalue(), headers=as_(tokens)
        )

    assert response.status_code == 400
    reasons = [
        r.reason for r in caplog.records if getattr(r, "code", "") == "package_unsafe_path"
    ]
    assert len(reasons) == 1
    assert "\n" not in reasons[0], "escaped, or the name writes its own log line"
    assert "\\n" in reasons[0]
    assert len(reasons[0]) <= api_module._GUARD_REASON_CHARS


def test_a_symlink_inside_the_archive_is_refused(client, tokens):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        info = zipfile.ZipInfo("tasks/link.md")
        # The mode lives in the high 16 bits of the external attributes, which is
        # how a zip says "this entry is a link, not a file".
        info.external_attr = (0o120777 << 16)
        archive.writestr(info, "/etc/passwd")

    response = client.post(
        "/v1/datasets/packages?id=link", content=buffer.getvalue(), headers=as_(tokens)
    )

    assert response.status_code == 400
    assert response.json()["error"] == "package_unsafe_path"


def test_an_archive_this_build_cannot_decode_is_a_refusal_not_a_crash(
    client, tokens, tmp_path
):
    """The directory is checked; the compression method is only read on open().

    A package packed by a tool this build does not know therefore fails inside the
    write loop, as ``NotImplementedError`` -- a shape no route handles, which used
    to cost the uploader a 500 for a file they can go and re-pack.
    """
    response = client.post(
        "/v1/datasets/packages?id=method",
        content=_recompress(package_bytes(tmp_path, "cust_a")),
        headers=as_(tokens),
    )

    assert response.status_code == 422
    assert response.json()["error"] == "package_invalid"
    assert client.get("/v1/datasets/method", headers=as_(tokens)).status_code == 404


def test_two_members_wanting_one_spot_say_which_one_lost(client, tokens):
    """``tasks/a.md`` as a file and ``tasks/a.md/ghost.md`` as a path cannot land.

    Both names are well-formed, so the checks above the loop pass and the collision
    only happens when the second asks the first's file to be a directory.  The
    member that lost travels in the message because ``package_invalid`` alone gives
    the uploader nothing to re-pack.
    """
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("tasks/a.md", "---\nid: a\n---\n\nprompt\n")
        archive.writestr("tasks/a.md/ghost.md", b"content")

    response = client.post(
        "/v1/datasets/packages?id=collide",
        content=buffer.getvalue(),
        headers=as_(tokens),
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "package_invalid"
    assert "tasks/a.md/ghost.md" in payload["message"]
    assert client.get("/v1/datasets/collide", headers=as_(tokens)).status_code == 404


def test_a_body_that_is_not_a_zip_is_refused(client, tokens):
    response = client.post(
        "/v1/datasets/packages?id=notzip", content=b"markdown text", headers=as_(tokens)
    )

    assert response.status_code == 400
    assert response.json()["error"] == "package_not_zip"


def test_an_archive_over_the_quota_is_refused_before_it_lands(
    client, tokens, tmp_path, monkeypatch
):
    monkeypatch.setattr(dataset_module, "MAX_PACKAGE_BYTES", 400)

    response = client.post(
        "/v1/datasets/packages?id=big",
        content=package_bytes(tmp_path, "cust_a", "cust_b"),
        headers=as_(tokens),
    )

    assert response.status_code == 413
    assert response.json()["error"] == "package_too_large"
    # The route's own gate, not the unpacker's: the bytes never reached a temp
    # file, so there is nothing here to clean up after the refusal.
    assert "is over" in response.json()["message"]
    assert client.get("/v1/datasets/big", headers=as_(tokens)).status_code == 404


def test_uploading_over_another_subjects_id_keeps_theirs(client, tokens, tmp_path):
    client.post(
        "/v1/datasets/packages?id=shared&name=First",
        content=package_bytes(tmp_path, "cust_a"),
        headers=as_(tokens),
    )

    response = client.post(
        "/v1/datasets/packages?id=shared&name=Second",
        content=package_bytes(tmp_path, "cust_b"),
        headers=as_(tokens, "dev-2"),
    )

    assert response.status_code == 409
    assert response.json()["error"] == "dataset_exists"
    assert client.get("/v1/datasets/shared", headers=as_(tokens)).json()["name"] == "First"


def test_an_upload_and_a_view_cannot_cross_over_the_same_owner(
    client, tokens, tmp_path
):
    """The kind is fixed for the life of an id, even for the subject who owns it.

    ``upsert_dataset`` never rewrites ``kind``, so before this guard a second
    create with the *owner's* id swapped ``task_ids`` and ``filter_spec`` under a
    row the catalogue still described as the other kind -- a dataset whose
    listing lied about what it held, and whose results were reproduced from
    snapshot rows that no longer matched the files.
    """
    client.post(
        "/v1/datasets",
        json={"id": "cross-1", "filter": {"environment": "open"}},
        headers=as_(tokens),
    )
    client.post(
        "/v1/datasets/packages?id=cross-2",
        content=package_bytes(tmp_path, "cust_a"),
        headers=as_(tokens),
    )

    over_a_view = client.post(
        "/v1/datasets/packages?id=cross-1",
        content=package_bytes(tmp_path, "cust_b"),
        headers=as_(tokens),
    )
    over_a_package = client.post(
        "/v1/datasets",
        json={"id": "cross-2", "filter": {"environment": "open"}},
        headers=as_(tokens),
    )

    assert over_a_view.status_code == 400
    assert over_a_view.json()["error"] == "dataset_kind_fixed"
    assert over_a_package.status_code == 400
    assert over_a_package.json()["error"] == "dataset_kind_fixed"
    assert client.get("/v1/datasets/cross-1", headers=as_(tokens)).json()["kind"] == (
        "builtin_view"
    )
    assert client.get("/v1/datasets/cross-2", headers=as_(tokens)).json()["kind"] == "custom"


def test_an_upload_needs_an_id_too(client, tokens, tmp_path):
    response = client.post(
        "/v1/datasets/packages", content=package_bytes(tmp_path, "cust_a"), headers=as_(tokens)
    )

    assert response.status_code == 400
    assert response.json()["error"] == "field_missing"


# ── what an upload may ask of the machine ─────────────────────────────────────


class _CountedDatasets:
    """The real service with a count of how many packages are inside it.

    The upload route spends the disk twice -- streaming the archive to a temp
    file, then unpacking it.  This class can only see the second, so the first is
    counted by the test around the module's own streaming helper.
    """

    def __init__(self, inner: DatasetService) -> None:
        self._inner = inner
        self._gate = threading.Lock()
        self.inside = 0
        self.peak = 0
        self.landed = 0
        # The streaming phase, counted by the test around the module's own helper:
        # this class cannot see it, because it happens before the call arrives.
        self.writing = 0
        self.writing_peak = 0

    def register_custom_archive(self, **kwargs: Any) -> Any:
        with self._gate:
            self.inside += 1
            self.peak = max(self.peak, self.inside)
        try:
            # Long enough that a third arrival would overlap if nothing stopped
            # it; the sleep is in the worker thread ``to_thread`` handed it, so
            # it does not stall the loop the other two are running on.
            time.sleep(0.05)
            record = self._inner.register_custom_archive(**kwargs)
            with self._gate:
                self.landed += 1
            return record
        finally:
            with self._gate:
                self.inside -= 1

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def test_two_packages_land_and_a_third_waits_its_turn(
    config: EvalConfig,
    store: Store,
    queue: JobQueue,
    datasets: DatasetService,
    clock: FrozenClock,
    allowlist: Path,
    tokens: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three simultaneous uploads, two temp files -- the cap is the point.

    A size gate says one package fits; it says nothing about how many arrive at
    once, and the thread pool this app answers them from is wider than the disk.
    The third caller is queued rather than refused, which is why all three come
    back 201: the bytes arrived, it simply was not their turn to be written.

    Both phases are counted because the gate is one ``async with`` around both.
    Watching only the service call would still pass if the gate moved inward, to
    the unpack alone -- and the three bodies streaming into temp files at once is
    the half of this that fills a disk first.
    """
    spy = _CountedDatasets(datasets)
    real_stream = api_module._stream_body_to_file

    async def count_the_stream(request: Any, limit: int, package_dir: Path) -> Path:
        with spy._gate:
            spy.writing += 1
            spy.writing_peak = max(spy.writing_peak, spy.writing)
        try:
            return await real_stream(request, limit, package_dir)
        finally:
            with spy._gate:
                spy.writing -= 1

    monkeypatch.setattr(api_module, "_stream_body_to_file", count_the_stream)
    app = build_control_app(
        store=store,
        config=config,
        queue=queue,
        datasets=spy,
        allowlist=allowlist,
        tmp_path=tmp_path,
        clock=clock,
    )
    bodies = [package_bytes(tmp_path, f"cust_{index}") for index in range(3)]

    async def upload_three() -> list[Any]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://svc") as http:
            return await asyncio.gather(
                *(
                    http.post(
                        f"/v1/datasets/packages?id=cust-{index}",
                        content=bodies[index],
                        headers=as_(tokens),
                    )
                    for index in range(3)
                )
            )

    responses = asyncio.run(upload_three())

    assert [response.status_code for response in responses] == [201, 201, 201]
    assert spy.landed == 3
    # Three arrivals never all hold a file at once, and the number the operator
    # is promised is the number this route used.
    assert spy.peak == api_module.MAX_CONCURRENT_PACKAGE_UPLOADS
    assert spy.peak < 3
    assert spy.writing_peak == api_module.MAX_CONCURRENT_PACKAGE_UPLOADS
    assert spy.writing_peak < 3


def test_a_disk_without_room_is_said_before_the_package_arrives(
    client: TestClient, tokens: dict[str, str], tmp_path: Path, monkeypatch, caplog
) -> None:
    """507 and not 413: the set is a size this service takes, the machine is out.

    Two refusals that look the same to the caller mean opposite things to whoever
    reads the log -- one says "pack a smaller set", the other says "the volume the
    uploads land on is full" -- so the byte counts have to reach the record, and
    the check has to run before a temp file exists.  A half-written archive is the
    thing being avoided, not the thing being reported.
    """
    volumes: list[Path] = []

    def full_disk(path: Any) -> Any:
        volumes.append(Path(path))
        return SimpleNamespace(total=2_000_000, used=2_000_000, free=0)

    def refuse_to_open(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a temp file was opened before the room was checked")

    monkeypatch.setattr(api_module.shutil, "disk_usage", full_disk)
    monkeypatch.setattr(api_module.tempfile, "mkstemp", refuse_to_open)

    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/v1/datasets/packages?id=full",
            content=package_bytes(tmp_path, "cust_a"),
            headers=as_(tokens),
        )

    assert response.status_code == 507
    assert response.json()["error"] == "package_disk_full"
    assert client.get("/v1/datasets/full", headers=as_(tokens)).status_code == 404
    assert volumes == [Path(tempfile.gettempdir())], "the volume the bytes would land on"
    told = [r for r in caplog.records if getattr(r, "code", "") == "package_disk_full"]
    assert [(r.subject, r.dataset_id, r.levelno) for r in told] == [
        ("dev-1", "full", logging.WARNING)
    ]
    assert "0 bytes free" in told[0].reason


def test_a_full_package_volume_is_refused_though_the_temp_directory_is_empty(
    client: TestClient,
    config: EvalConfig,
    tokens: dict[str, str],
    tmp_path: Path,
    monkeypatch,
    caplog,
) -> None:
    """Two volumes, because the request writes to two places that need not share one.

    The archive lands in the temp directory and its unpacked copy lands in the
    package directory; on a box where ``/tmp`` is tmpfs those are different
    questions, and measuring only the temp directory passes while the copy fills
    the volume the database, the transcripts and the reports live on.
    """
    volumes: list[Path] = []

    def roomy_here_full_there(path: Any) -> Any:
        volume = Path(path)
        volumes.append(volume)
        free = 5_000_000_000 if volume == Path(tempfile.gettempdir()) else 0
        return SimpleNamespace(total=5_000_000_000, used=5_000_000_000 - free, free=free)

    def refuse_to_open(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("a temp file was opened before the room was checked")

    monkeypatch.setattr(api_module.shutil, "disk_usage", roomy_here_full_there)
    monkeypatch.setattr(api_module.tempfile, "mkstemp", refuse_to_open)

    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/v1/datasets/packages?id=fillsup",
            content=package_bytes(tmp_path, "cust_a"),
            headers=as_(tokens),
        )

    assert response.status_code == 507
    assert response.json()["error"] == "package_disk_full"
    # Both were asked, and the second is the one that said no.
    assert len(volumes) == 2
    assert Path(tempfile.gettempdir()) in volumes
    assert any(
        volume == config.datasets.custom_dir or volume in config.datasets.custom_dir.parents
        for volume in volumes[1:]
    )
    told = [r for r in caplog.records if getattr(r, "code", "") == "package_disk_full"]
    assert "0 bytes free" in told[0].reason
    assert str(volumes[1]) in told[0].reason


def test_a_write_that_fails_under_the_pre_flight_is_the_same_refusal(
    client: TestClient, tokens: dict[str, str], tmp_path: Path, monkeypatch, caplog
) -> None:
    """The volume filling mid-upload is the same fact, told the same way.

    The pre-flight reads what the caller declared; somebody else's write can still
    take the room between that check and the last chunk.  Left unmapped it reaches
    the generic handler as a ``logger.error`` and a status nobody chose, which is
    the shape L19 spent this batch removing from the rest of the service.
    """
    def closed_pipe_descriptor(*args: Any, **kwargs: Any) -> tuple[int, str]:
        # An fd this route can open and hand to the writer, that fails the moment
        # the bytes are flushed: the reader's end is gone before the first chunk.
        read_end, write_end = os.pipe()
        os.close(read_end)
        return write_end, str(tmp_path / "closed-pipe.zip")

    monkeypatch.setattr(api_module.tempfile, "mkstemp", closed_pipe_descriptor)

    with caplog.at_level(logging.WARNING):
        response = client.post(
            "/v1/datasets/packages?id=halfway",
            content=package_bytes(tmp_path, "cust_a"),
            headers=as_(tokens),
        )

    assert response.status_code == 507
    assert response.json()["error"] == "package_disk_full"
    told = [r for r in caplog.records if getattr(r, "code", "") == "package_disk_full"]
    assert [r.levelno for r in told] == [logging.WARNING]
    assert "bytes" in told[0].reason


# ── deletion ──────────────────────────────────────────────────────────────────


def test_a_dataset_somebody_ran_against_cannot_be_deleted(client, tokens):
    submitted = client.post(
        "/v1/jobs",
        json={
            "acp_url": ACP_URL,
            "selector": {"datasets": ["mail"]},
            "window": {"kind": "immediate"},
            "product": "qwenpaw",
            "purpose": "replay",
        },
        headers=as_(tokens),
    )
    assert submitted.status_code == 201, submitted.text

    response = client.delete("/v1/datasets/mail", headers=as_(tokens))

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"] == "dataset_referenced"
    assert payload["details"]["job_ids"] == [submitted.json()["job_id"]]


def test_the_owner_deletes_an_unused_dataset_and_it_goes_404_after(client, tokens):
    client.post(
        "/v1/datasets", json={"id": "temp", "filter": {"environment": "open"}}, headers=as_(tokens)
    )

    assert client.delete("/v1/datasets/temp", headers=as_(tokens)).status_code == 204
    assert client.get("/v1/datasets/temp", headers=as_(tokens)).status_code == 404


def test_deleting_another_subjects_dataset_is_403_not_404(client, tokens):
    response = client.delete("/v1/datasets/mail", headers=as_(tokens, "dev-2"))

    assert response.status_code == 403
    assert response.json()["error"] == "not_dataset_owner"


# ── categories ────────────────────────────────────────────────────────────────


def test_a_category_is_created_once_however_two_people_spelled_it(client, tokens):
    first = client.post(
        "/v1/dataset-categories", json={"name": "Office Productivity"}, headers=as_(tokens)
    )
    second = client.post(
        "/v1/dataset-categories",
        json={"name": "office  productivity"},
        headers=as_(tokens, "dev-2"),
    )

    assert first.status_code == 201, first.text
    assert first.json()["name"] == "office productivity"
    assert first.json()["created"] is True
    assert second.json()["name"] == "office productivity"
    assert second.json()["created"] is False, "the selector must not see two of these"
    listing = client.get("/v1/dataset-categories", headers=as_(tokens)).json()["categories"]
    names = [item["name"] for item in listing]
    assert names.count("office productivity") == 1


def test_anybody_on_the_list_may_create_a_category_but_not_unmake_another_s(
    client, tokens
):
    created = client.post(
        "/v1/dataset-categories", json={"name": "nightly"}, headers=as_(tokens, "dev-2")
    )
    assert created.status_code == 201

    stranger = client.delete("/v1/dataset-categories/nightly", headers=as_(tokens))
    assert stranger.status_code == 403
    assert stranger.json()["error"] == "not_category_owner"

    mine = client.delete("/v1/dataset-categories/nightly", headers=as_(tokens, "dev-2"))
    assert mine.status_code == 204

    gone = client.delete("/v1/dataset-categories/nightly", headers=as_(tokens, "ops"))
    assert gone.status_code == 404


def test_a_category_still_filing_a_dataset_survives(client, tokens):
    response = client.delete("/v1/dataset-categories/email", headers=as_(tokens, "ops"))

    assert response.status_code == 409
    assert response.json()["error"] == "category_referenced"
    assert response.json()["details"]["dataset_count"] == 1


def test_a_category_name_that_normalises_to_nothing_is_refused(client, tokens):
    response = client.post(
        "/v1/dataset-categories", json={"name": "   "}, headers=as_(tokens)
    )

    assert response.status_code == 400
    assert response.json()["error"] == "field_missing"


# ── the token gate ────────────────────────────────────────────────────────────


def test_every_catalogue_route_refuses_an_absent_token(client):
    calls: list[Any] = [
        client.get("/v1/datasets"),
        client.post("/v1/datasets", json={"id": "x", "filter": {"environment": "open"}}),
        client.get("/v1/datasets/mail"),
        client.put("/v1/datasets/mail", json={"filter": {"environment": "open"}}),
        client.delete("/v1/datasets/mail"),
        client.post("/v1/datasets/packages?id=x", content=b"zip"),
        client.get("/v1/dataset-categories"),
        client.post("/v1/dataset-categories", json={"name": "x"}),
        client.delete("/v1/dataset-categories/email"),
    ]

    assert [response.status_code for response in calls] == [401] * len(calls)
    assert {response.json()["error"] for response in calls} == {"unauthenticated"}


# ── the drill-down: one task of one dataset ───────────────────────────────────


def test_one_task_of_a_dataset_answers_with_its_prompt(client, tokens):
    """The listing refuses bodies; this route is the deliberate way in.

    Both halves are asserted together because the distinction is the whole
    design: a listing that quotes the question tells the subject what is
    expected before it answered anything, while a reader who has opened one
    task has asked for that task.
    """
    response = client.get("/v1/datasets/mail/tasks/mail_l1", headers=as_(tokens))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == "mail_l1"
    assert PROMPT_MARK in body["prompt"]
    assert body["labels"]["scenario"] == "Office_Productivity/Email"
    assert body["attachments"] == []
    # The rules travel with the question; the grading code does not.
    assert "automated_checks" not in body
    assert set(body) >= {"grading_criteria", "llm_judge_rubric", "has_automated_checks"}
    # Still true of the listing, which is the route the picker reads.
    assert PROMPT_MARK not in client.get("/v1/datasets/mail", headers=as_(tokens)).text


def test_a_task_markdown_can_be_read_when_the_fields_come_back_thin(client, tokens, tmp_path):
    """The button beside the rubric: the file itself, through the same reader."""
    source = tmp_path / "pkg"
    write_task(source, "with_file", scenario="Custom/One", fixtures=("budget.txt",))
    client.post(
        "/v1/datasets/packages?id=cust-src&name=Source",
        content=zip_package(source),
        headers=as_(tokens),
    )

    response = client.get("/v1/datasets/cust-src/tasks/with_file/source", headers=as_(tokens))

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "text"
    assert "## Prompt" in body["text"]
    assert PROMPT_MARK in body["text"]


def test_a_task_outside_the_dataset_answers_its_own_404(client, tokens):
    response = client.get("/v1/datasets/mail/tasks/chart_open", headers=as_(tokens))

    assert response.status_code == 404
    assert response.json()["error"] == "task_not_in_dataset"


def test_a_package_fixture_can_be_previewed_and_a_stray_path_is_422(
    client, tokens, tmp_path
):
    """One path policy: what the exchange would refuse to serve a run, this
    route refuses to show a browser."""
    source = tmp_path / "pkg"
    write_task(source, "with_file", scenario="Custom/One", fixtures=("budget.txt",))
    uploaded = client.post(
        "/v1/datasets/packages?id=cust-files&name=Files",
        content=zip_package(source),
        headers=as_(tokens),
    )
    assert uploaded.status_code == 201, uploaded.text

    task = client.get("/v1/datasets/cust-files/tasks/with_file", headers=as_(tokens)).json()
    assert task["attachments"] == [
        {"path": "fixtures/budget.txt", "size": len("content of budget.txt"), "present": True}
    ]

    preview = client.get(
        "/v1/datasets/cust-files/tasks/with_file/attachments/preview",
        params={"path": "fixtures/budget.txt"},
        headers=as_(tokens),
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["kind"] == "text"
    assert preview.json()["text"] == "content of budget.txt"

    undeclared = client.get(
        "/v1/datasets/cust-files/tasks/with_file/attachments/preview",
        params={"path": "tasks/with_file.md"},
        headers=as_(tokens),
    )
    assert undeclared.status_code == 404
    assert undeclared.json()["error"] == "attachment_not_found"

    escaping = client.get(
        "/v1/datasets/cust-files/tasks/with_file/attachments/preview",
        params={"path": "../outside.txt"},
        headers=as_(tokens),
    )
    assert escaping.status_code == 422
    assert escaping.json()["error"] == "bad_attachment_path"
