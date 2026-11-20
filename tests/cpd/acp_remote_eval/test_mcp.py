"""MCP transport and whitelist authentication against a real service instance."""

from __future__ import annotations

import asyncio
import base64

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from pawbench.cpd.acp_remote_eval.mcp.server import MAX_MCP_ARCHIVE_BYTES, _package_archive
from pawbench.cpd.acp_remote_eval.service.datasets import DatasetError
from pawbench.cpd.acp_remote_eval.service import daemon
from pawbench.cpd.acp_remote_eval.service.auth import (
    SCOPE_SUBMIT,
    StaticConfigVerifier,
    TokenRecord,
    token_sha256,
)
from support import eval_config, write_task, zip_package

TOKEN = "fake-mcp-token-for-tests"


def test_mcp_archive_rejects_invalid_and_oversized_payloads() -> None:
    with pytest.raises(DatasetError, match="base64"):
        _package_archive("not-base64!")
    with pytest.raises(DatasetError, match="512 KiB"):
        _package_archive("A" * (MAX_MCP_ARCHIVE_BYTES * 2))


def test_mcp_requires_whitelist_and_lists_real_datasets(tmp_path, monkeypatch) -> None:
    builtin = tmp_path / "builtin"
    write_task(builtin, "mail_a", scenario="Office_Productivity/Email")
    custom = tmp_path / "custom-package"
    write_task(custom, "custom_a")
    archive_base64 = base64.b64encode(zip_package(custom, root="dataset")).decode("ascii")
    invalid = tmp_path / "invalid-package"
    write_task(invalid, "invalid_a")
    (invalid / "tasks" / "conftest.py").write_text("pass\n", encoding="utf-8")
    invalid_base64 = base64.b64encode(zip_package(invalid)).decode("ascii")
    config = eval_config(tmp_path / "service", builtin_root=builtin)
    verifier = StaticConfigVerifier(
        [TokenRecord(subject="reviewer", token_hash=token_sha256(TOKEN),
                     scopes=frozenset({SCOPE_SUBMIT}))]
    )
    monkeypatch.setattr(daemon, "build_verifier", lambda config: verifier)
    service = daemon.build_service(config)

    async def exercise() -> None:
        async with service.app.router.lifespan_context(service.app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=service.app),
                base_url="http://127.0.0.1:8471",
            ) as anonymous:
                response = await anonymous.get("/mcp/")
                assert response.status_code == 401
                denied = await anonymous.post(
                    "/mcp/",
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                    headers={"accept": "application/json, text/event-stream"},
                )
                assert denied.status_code == 401
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=service.app),
                base_url="http://127.0.0.1:8471",
                headers={"Authorization": f"Bearer {TOKEN}"},
            ) as client:
                async with streamable_http_client(
                    "http://127.0.0.1:8471/mcp/", http_client=client
                ) as (reader, writer, _):
                    async with ClientSession(reader, writer) as session:
                        await session.initialize()
                        tools = await session.list_tools()
                        names = {tool.name for tool in tools.tools}
                        assert "pawbench_list_datasets" in names
                        assert "pawbench_submit_job" in names
                        assert "pawbench_cancel_job" in names
                        assert "pawbench_get_transcript" in names
                        assert "pawbench_validate_dataset_package" in names
                        assert "pawbench_create_custom_dataset" in names
                        valid = await session.call_tool(
                            "pawbench_validate_dataset_package",
                            {"archive_base64": archive_base64},
                        )
                        assert not valid.isError
                        assert valid.structuredContent["ok"] is True
                        assert valid.structuredContent["task_ids"] == ["custom_a"]
                        rejected = await session.call_tool(
                            "pawbench_validate_dataset_package",
                            {"archive_base64": invalid_base64},
                        )
                        assert not rejected.isError
                        assert rejected.structuredContent["ok"] is False
                        assert any(item["code"] == "forbidden_file_name"
                                   for item in rejected.structuredContent["items"])
                        custom_created = await session.call_tool(
                            "pawbench_create_custom_dataset",
                            {"dataset_id": "custom-mcp", "archive_base64": archive_base64},
                        )
                        assert not custom_created.isError
                        assert service.datasets.get("custom-mcp")["owner"] == "reviewer"
                        refused = await session.call_tool(
                            "pawbench_create_custom_dataset",
                            {"dataset_id": "invalid-mcp", "archive_base64": invalid_base64},
                        )
                        assert refused.isError
                        assert service.store.get_dataset("invalid-mcp") is None
                        result = await session.call_tool("pawbench_list_datasets")
                        assert not result.isError
                        assert result.structuredContent is not None
                        created = await session.call_tool(
                            "pawbench_create_dataset",
                            {"dataset_id": "mcp-view", "name": "MCP view",
                             "filter_spec": {"task_ids": ["mail_a"]}},
                        )
                        assert not created.isError
                        assert service.datasets.get("mcp-view")["owner"] == "reviewer"
                        resolved = await session.call_tool(
                            "pawbench_resolve_selector",
                            {"selector": {"datasets": ["mcp-view"]}},
                        )
                        assert not resolved.isError
                        assert resolved.structuredContent is not None
                        submitted = await session.call_tool(
                            "pawbench_submit_job",
                            {"body": {
                                "acp_url": "http://127.0.0.1:9000/agent",
                                "selector": {"datasets": ["mcp-view"]},
                                "window": {"kind": "immediate"},
                                "product": "qwenpaw", "purpose": "MCP test",
                            }},
                        )
                        assert not submitted.isError
                        assert submitted.structuredContent is not None
                        job_id = submitted.structuredContent["job_id"]
                        listed = await session.call_tool("pawbench_list_jobs")
                        assert any(
                            job["job_id"] == job_id
                            for job in listed.structuredContent["jobs"]
                        )
                        canceled = await session.call_tool(
                            "pawbench_cancel_job", {"job_id": job_id}
                        )
                        assert not canceled.isError
                        assert service.jobs.get(job_id)["status"] == "canceled"

    try:
        asyncio.run(exercise())
    finally:
        service.store.close()
