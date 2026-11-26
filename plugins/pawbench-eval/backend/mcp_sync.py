# -*- coding: utf-8 -*-
"""Keep QwenPaw's MCP client in step with this plugin's connection settings.

The ``pawbench-datasets`` skill is gated on an MCP server named
``pawbench-eval`` (``metadata.qwenpaw.requires.mcp`` in its SKILL.md, checked by
``agents/skill_system/registry.py::check_skill_dependencies``).  Until that
client exists the skill is not in the list at all, and the endpoint it needs is
a fact this plugin already stores: ``<base_url>/mcp`` plus the bearer token.
Typing it a second time into 智能体 → MCP is a copy that goes stale the first
time somebody rotates a token, and the person who rotates it is not the person
who pasted it.  So the plugin writes the client itself.

Four rules keep that honest:

* **QwenPaw's own service is the only writer.**  Cards are created and updated
  through ``app/mcp/config_service.MCPConfigService``, so the result is the file
  the console would have written: ``<workspace>/drivers/mcp/pawbench-eval.yaml``
  with the token in the credential store rather than in the header.  Nothing
  here touches the YAML by hand.
* **The card is derived state.**  A save on the 配置 page rewrites it; plugin
  startup reconciles it; ``on_uninstall`` removes it.  Nothing reads it back to
  decide what the service address is -- ``data/config.json`` (or the
  ``PAWBENCH_EVAL_*`` environment) stays the one source.
* **Only cards this plugin wrote are removed.**  Somebody who pasted their own
  ``pawbench-eval`` card by hand keeps it: the description marker is what makes
  a card ours, and a card without it is left alone.
* **Nothing here is fatal.**  A host without the MCP service, or one workspace
  that refuses the card, logs a line and leaves the dashboard working.  The
  page does not need the skill to submit a job, so a failure here must never
  become a failed request.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

#: The key, the file name and the card name are all this one string: the skill
#: gate matches ``card.name`` against the name its front matter asks for, and
#: ``card_paths_for_name`` matches the file stem.  Renaming it here without
#: renaming the SKILL.md leaves the skill permanently invisible.
CLIENT_KEY = "pawbench-eval"

#: Written into the card description so a later uninstall can tell a card this
#: plugin created from one a person pasted.  The substring below is the marker;
#: the full string is what a reader sees in 智能体 → MCP.
DESCRIPTION = "PawBench 评测服务（由 pawbench-eval 插件自动配置）"
MANAGED_MARK = "pawbench-eval 插件自动配置"


def desired(base_url: str, token: str) -> dict[str, Any]:
    """The MCP client this plugin's settings describe.

    ``streamable_http`` and the ``/mcp`` suffix are the service's own contract
    (``service/api.py`` mounts the MCP app there), not a preference.  The token
    travels as an ``Authorization`` header, which QwenPaw classifies as a secret
    and moves into the credential store -- the card keeps a reference, not the
    value.
    """
    return {
        "name": CLIENT_KEY,
        "description": DESCRIPTION,
        "enabled": True,
        "transport": "streamable_http",
        "url": f"{base_url.rstrip('/')}/mcp",
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _service(workspace: Any) -> Any:
    """The host's MCP config service for one workspace.

    Imported lazily: this module is loaded by the plugin under QwenPaw, but the
    repository's own test suite imports the backend without QwenPaw installed.
    """
    from qwenpaw.app.mcp.config_service import MCPConfigService

    return MCPConfigService(workspace)


def _agents() -> dict[str, Any]:
    """The host's agent id → workspace map.

    ``PluginRegistry`` is where the PawApp SDK itself looks for it
    (``plugins/api.py::_get_all_workspaces``); there is no public accessor, and
    a plugin that only configured one workspace would leave the skill missing in
    every other agent the user created.
    """
    from qwenpaw.plugins.registry import PluginRegistry

    manager = PluginRegistry().get_workspace_manager()
    return dict(getattr(manager, "agents", None) or {})


def _workspaces() -> list[Any]:
    """Every agent workspace the host currently runs."""
    return list(_agents().values())


def workspace_for(workspace_info: dict[str, Any]) -> Optional[Any]:
    """The workspace instance a ``workspace_created`` payload names.

    The host documents that payload as ``agent_id`` + ``workspace_dir`` and adds
    the instance itself only during a reload (``plugins/api.py:557``).  A hook
    that reads nothing but ``workspace_info["workspace"]`` therefore works when
    a config is reloaded and does nothing on the path that actually matters:
    somebody creating an agent.
    """
    info = workspace_info or {}
    workspace = info.get("workspace")
    if workspace is not None:
        return workspace
    agent_id = info.get("agent_id")
    if not agent_id:
        return None
    return _agents().get(agent_id)


async def sync_workspace(
    workspace: Any,
    base_url: str,
    token: str,
    *,
    force: bool = False,
    service: Optional[Any] = None,
) -> str:
    """Create, update, or leave alone the ``pawbench-eval`` client here.

    Returns one of ``created`` / ``updated`` / ``unchanged`` / ``skipped``.

    ``force`` rewrites the card even when the URL already matches, which is what
    a save on the 配置 page wants: the token is masked on the way back out of
    the host, so "same URL" does not mean "same credential", and a rotated token
    has to reach the card somehow.  Startup reconciles from the token it already
    gave the host and therefore skips the write -- including the ``enabled``
    flag, because somebody who switched the client off in 智能体 → MCP meant it,
    and a restart is not an argument.  Saving the form is, and that sets
    ``enabled`` back to true along with everything else.
    """
    if not (base_url and token):
        return "skipped"

    payload = desired(base_url, token)
    service = service or _service(workspace)

    from qwenpaw.app.mcp.schemas import (
        MCPClientCreateRequest,
        MCPClientUpdateRequest,
    )

    try:
        card = await service.load_card(CLIENT_KEY)
    except Exception:  # noqa: BLE001 - "no card yet" arrives as HTTP 404
        card = None

    if card is None:
        await service.create_client(
            CLIENT_KEY,
            MCPClientCreateRequest(**payload),
        )
        logger.info("[pawbench-eval] MCP client created for %s", _label(workspace))
        return "created"

    info = await service.build_info_from_card(card)
    if not force and info.url == payload["url"]:
        return "unchanged"

    await service.update_client(CLIENT_KEY, MCPClientUpdateRequest(**payload))
    logger.info("[pawbench-eval] MCP client updated for %s", _label(workspace))
    return "updated"


async def sync_all(
    base_url: str,
    token: str,
    *,
    force: bool = False,
    workspaces: Optional[Iterable[Any]] = None,
) -> dict[str, str]:
    """Reconcile every workspace; one failure does not stop the others.

    Returns ``{workspace: action}`` for the log line, and for the tests that
    assert a save reached all of them.
    """
    if not (base_url and token):
        return {}

    targets = list(workspaces) if workspaces is not None else _workspaces()
    actions: dict[str, str] = {}
    for workspace in targets:
        label = _label(workspace)
        try:
            actions[label] = await sync_workspace(
                workspace,
                base_url,
                token,
                force=force,
            )
        except Exception as exc:  # noqa: BLE001 - a broken workspace is not a crash
            actions[label] = f"failed: {exc}"
            logger.warning(
                "[pawbench-eval] could not configure MCP for %s: %s",
                label,
                exc,
            )
    if actions:
        logger.info("[pawbench-eval] MCP sync: %s", actions)
    return actions


async def remove_workspace(workspace: Any, *, service: Optional[Any] = None) -> str:
    """Delete the client on uninstall, unless somebody else owns it.

    Returns ``removed`` / ``absent`` / ``kept``.
    """
    service = service or _service(workspace)
    try:
        card = await service.load_card(CLIENT_KEY)
    except Exception:  # noqa: BLE001 - nothing to remove is the happy path
        return "absent"

    description = str((getattr(card, "config", None) or {}).get("description") or "")
    if MANAGED_MARK not in description:
        # A hand-written card can carry rules, a whitelist or a different
        # endpoint.  Uninstalling the dashboard is not a reason to take it away.
        logger.info(
            "[pawbench-eval] leaving MCP client %s alone: not configured by this plugin",
            _label(workspace),
        )
        return "kept"

    await service.delete_client(CLIENT_KEY)
    logger.info("[pawbench-eval] MCP client removed from %s", _label(workspace))
    return "removed"


async def remove_all(workspaces: Optional[Iterable[Any]] = None) -> dict[str, str]:
    """Uninstall side of :func:`sync_all`."""
    targets = list(workspaces) if workspaces is not None else _workspaces()
    actions: dict[str, str] = {}
    for workspace in targets:
        label = _label(workspace)
        try:
            actions[label] = await remove_workspace(workspace)
        except Exception as exc:  # noqa: BLE001 - uninstall must not raise
            actions[label] = f"failed: {exc}"
            logger.warning(
                "[pawbench-eval] could not remove MCP client from %s: %s",
                label,
                exc,
            )
    return actions


def _label(workspace: Any) -> str:
    return str(getattr(workspace, "workspace_dir", "") or workspace)
