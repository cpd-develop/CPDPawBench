"""Expose the service's existing dataset and job operations through MCP."""

from __future__ import annotations

import asyncio
import base64
import binascii
import contextvars
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from ..service.api import ControlPlane
from ..service.auth import AuthError, Principal, SCOPE_SUBMIT
from ..service.datasets import DatasetError, unpack_package, validate_package

MAX_MCP_ARCHIVE_BYTES = 512 * 1024
_principal: contextvars.ContextVar[Principal] = contextvars.ContextVar("pawbench_mcp_principal")


def _package_archive(archive_base64: str) -> bytes:
    if len(archive_base64) > ((MAX_MCP_ARCHIVE_BYTES + 2) // 3) * 4:
        raise DatasetError("package_too_large", "MCP packages are limited to 512 KiB; use the HTTP upload endpoint for larger packages")
    try:
        archive = base64.b64decode(archive_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise DatasetError("package_not_base64", "package must be base64-encoded zip bytes") from exc
    if len(archive) > MAX_MCP_ARCHIVE_BYTES:
        raise DatasetError("package_too_large", "MCP packages are limited to 512 KiB; use the HTTP upload endpoint for larger packages")
    return archive


def _custom_package(
    control: ControlPlane, archive_base64: str, dataset_id: str | None = None,
    name: str = "", owner: str = "", categories: list[str] | None = None,
    description: str = "",
) -> dict[str, Any]:
    archive_bytes = _package_archive(archive_base64)
    with tempfile.TemporaryDirectory(prefix="pawbench-mcp-package-") as staging:
        path = Path(staging) / "package.zip"
        path.write_bytes(archive_bytes)
        if dataset_id is not None:
            return control.datasets.register_custom_archive(
                dataset_id=dataset_id, name=name, owner=owner, archive=path,
                categories=categories or (), description=description,
            )
        unpacked = Path(staging) / "unpacked"
        unpacked.mkdir()
        unpack_package(path, unpacked)
        return validate_package(unpacked).as_payload()



class BearerGate:
    """Verify every HTTP exchange before MCP can list or invoke tools."""

    def __init__(self, app: ASGIApp, control: ControlPlane) -> None:
        self.app = app
        self.control = control

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {key.lower(): value for key, value in scope["headers"]}
        authorization = headers.get(b"authorization", b"").decode("latin-1")
        scheme, separator, token = authorization.partition(" ")
        try:
            if scheme.lower() != "bearer" or not separator:
                raise AuthError("unauthenticated", "a bearer token is required")
            principal = await asyncio.to_thread(
                self.control.verifier.verify, token.strip(), SCOPE_SUBMIT
            )
        except AuthError as exc:
            await JSONResponse(
                {"error": exc.code, "message": exc.message}, status_code=exc.status
            )(scope, receive, send)
            return
        bound = _principal.set(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            _principal.reset(bound)


def create_mcp(control: ControlPlane, public_base_url: str, log_level: str) -> FastMCP:
    """Register tools over the same services used by the HTTP control plane."""
    public_address = urlsplit(public_base_url)
    server = FastMCP(
        "pawbench-eval", stateless_http=True, json_response=True,
        streamable_http_path="/", mount_path="/",
        log_level=log_level,
        transport_security=TransportSecuritySettings(
            allowed_hosts=[public_address.netloc],
            allowed_origins=[f"{public_address.scheme}://{public_address.netloc}"],
        ),
    )

    @server.tool()
    async def pawbench_list_datasets() -> dict[str, Any]:
        return await asyncio.to_thread(control.datasets.list_catalog)

    @server.tool()
    async def pawbench_describe_dataset(dataset_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(control.datasets.describe, dataset_id)

    @server.tool()
    async def pawbench_list_categories() -> list[dict[str, Any]]:
        return await asyncio.to_thread(control.datasets.list_categories)

    @server.tool()
    async def pawbench_resolve_selector(selector: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(control.datasets.resolve, selector)
        return result.to_payload()

    @server.tool()
    async def pawbench_create_dataset(
        dataset_id: str, name: str, filter_spec: dict[str, Any],
        categories: list[str] | None = None, description: str = "",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            control.datasets.create_builtin_view,
            dataset_id=dataset_id, name=name, owner=_principal.get().subject,
            filter_spec=filter_spec, categories=categories or (), description=description,
        )

    @server.tool()
    async def pawbench_validate_dataset_package(archive_base64: str) -> dict[str, Any]:
        """Validate a small ZIP without registering it; larger ZIPs use HTTP upload."""
        return await asyncio.to_thread(_custom_package, control, archive_base64)

    @server.tool()
    async def pawbench_create_custom_dataset(
        dataset_id: str, archive_base64: str, name: str = "",
        categories: list[str] | None = None, description: str = "",
    ) -> dict[str, Any]:
        """Register a validated ZIP as a dataset owned by the bearer subject."""
        return await asyncio.to_thread(
            _custom_package, control, archive_base64, dataset_id, name,
            _principal.get().subject, categories, description,
        )

    @server.tool()
    async def pawbench_manage_category(
        name: str, delete: bool = False, description: str = "",
    ) -> dict[str, Any]:
        principal = _principal.get()
        if delete:
            await asyncio.to_thread(control.datasets.delete_category, name, principal)
            return {"deleted": name}
        return await asyncio.to_thread(
            control.datasets.ensure_category, name, principal.subject, description
        )

    @server.tool()
    async def pawbench_assign_categories(
        dataset_id: str, add: list[str] | None = None,
        remove: list[str] | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            control.datasets.assign_categories, dataset_id, _principal.get(),
            add=add or (), remove=remove or (),
        )

    @server.tool()
    async def pawbench_submit_job(body: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(control.jobs.submit, body, _principal.get())

    @server.tool()
    async def pawbench_list_jobs(
        statuses: list[str] | None = None, submitter: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            control.jobs.list_jobs, statuses=statuses or (),
            submitter=submitter, limit=limit,
        )

    @server.tool()
    async def pawbench_reorder_job(
        job_id: str, before_id: str | None = None,
        after_id: str | None = None, queue_pos: float | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            control.jobs.reorder, job_id, _principal.get(),
            before_id=before_id, after_id=after_id, position=queue_pos,
        )

    @server.tool()
    async def pawbench_cancel_job(
        job_id: str, reason: str | None = None
    ) -> dict[str, Any]:
        outcome = await asyncio.to_thread(
            control.jobs.cancel, job_id, _principal.get(), error=reason
        )
        if outcome.get("was_running") and control.stop_running is not None:
            control.stop_running(job_id)
        return outcome

    @server.tool()
    async def pawbench_job_status(job_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(control.jobs.get, job_id)

    @server.tool()
    async def pawbench_job_results(job_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(control.reports.results, job_id)

    @server.tool()
    async def pawbench_get_job_detail(
        job_id: str, sensitivity: str = "shared",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(control.reports.job_detail, job_id, sensitivity)

    @server.tool()
    async def pawbench_get_task_detail(
        job_id: str, task_id: str, sensitivity: str = "shared",
        attempt: int | None = None,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            control.reports.task_detail, job_id, task_id, sensitivity, attempt
        )

    @server.tool()
    async def pawbench_get_transcript(
        job_id: str, task_id: str, attempt: int = 1,
        cursor: int = 0, limit: int = 100,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            control.reports.transcript, job_id, task_id,
            attempt=attempt, cursor=cursor, limit=limit,
        )

    @server.tool()
    async def pawbench_get_report(
        job_id: str, format: str = "json", sensitivity: str = "shared",
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            control.reports.report, job_id, fmt=format, sensitivity=sensitivity
        )

    return server


def mount_mcp(
    app: Any, control: ControlPlane, public_base_url: str, log_level: str
) -> None:
    """Share the daemon's lifespan with the stateless MCP session manager."""
    server = create_mcp(control, public_base_url, log_level)
    app.mount("/mcp", BearerGate(server.streamable_http_app(), control))
    app.router.lifespan_context = lambda _: server.session_manager.run()
