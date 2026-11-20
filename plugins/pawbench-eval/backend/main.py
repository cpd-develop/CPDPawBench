# -*- coding: utf-8 -*-
"""PawBench Eval — PawApp backend.

Two jobs, both deliberately small:

1. **Ship the skill.** ``pawbench-datasets`` goes into the workspace so an
   agent can prepare and catalogue datasets without a browser.
2. **Proxy ``/v1/*`` to the evaluation service.** The dashboard could call the
   service directly, but then the bearer token would live in the browser and
   every token holder would have to paste it into two places. Here the token
   stays on this side of the browser boundary: the page calls
   ``/api/pawbench-eval/v1/jobs``, this module adds the credential.

The proxy is transparent on purpose — same path, same query string, same
status code, same body. A field-by-field mapping would be a second contract to
keep in step with ``service/api.py``, and every drift would read as "the
dashboard is broken" rather than "the mapping is stale".
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from qwenpaw.pawapp import PawApp

logger = logging.getLogger(__name__)

# Runtime files live beside the plugin (``install`` copies the tree, so this is
# the installed copy, not the repository one).  Never derive anything from the
# repository path: README's install command points at the repo, the loader does
# a ``copytree``, and a path spelled with the repo's own layout works in a
# checkout and breaks on every other machine.
_APP_DIR = Path(__file__).resolve().parent.parent
_CONFIG_FILE = _APP_DIR / "data" / "config.json"
_PLUGIN_ROOT = _APP_DIR
_SKILLS_DIR = _PLUGIN_ROOT / "skills"

#: Env overrides, for a machine where nobody wants to click through the form
#: (CI, a demo box).  The form still wins when both are set: it is the thing
#: with a save button and therefore the thing a person believes.
_ENV_BASE = "PAWBENCH_EVAL_BASE_URL"
_ENV_TOKEN = "PAWBENCH_EVAL_TOKEN"

#: Read timeout per method.  A report over a full corpus compiles HTML and zips
#: artifacts, and a package upload streams a tarball; both are minutes-shaped,
#: everything else is one sqlite read.
_TIMEOUTS = {"GET": 60.0, "POST": 300.0, "PUT": 120.0, "PATCH": 60.0, "DELETE": 60.0}

_LOCK = threading.Lock()

router = APIRouter()


# ── config ────────────────────────────────────────────────────────────────


def _read_file_config() -> dict[str, Any]:
    try:
        raw = _CONFIG_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:  # noqa: BLE001 - a corrupt config must not brick the page
        logger.warning("[pawbench-eval] unreadable config %s: %s", _CONFIG_FILE, exc)
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("[pawbench-eval] config %s is not JSON", _CONFIG_FILE)
        return {}
    return data if isinstance(data, dict) else {}


def _effective() -> tuple[str, str, str]:
    """``(base_url, token, subject)`` with env standing in for a missing file."""
    data = _read_file_config()
    base = str(data.get("base_url") or "").strip() or os.environ.get(_ENV_BASE, "").strip()
    token = str(data.get("token") or "").strip() or os.environ.get(_ENV_TOKEN, "").strip()
    subject = str(data.get("subject") or "").strip()
    return base.rstrip("/"), token, subject


def _write_file_config(patch: dict[str, Any]) -> dict[str, Any]:
    """Merge *patch* into the stored config; ``token: ""`` clears it."""
    with _LOCK:
        data = _read_file_config()
        for key, value in patch.items():
            if value is None:
                continue
            data[key] = value
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CONFIG_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        # The file holds a bearer token and sits in a home directory other local
        # accounts can read.  ``mkstemp``-style creation with 0600 would be
        # better, but the write has to survive ``os.replace`` from a temp file,
        # and a chmod before the replace is what sets the mode that lands.
        try:
            os.chmod(tmp, 0o600)
        except OSError:  # pragma: no cover - a filesystem with no mode bits
            logger.warning("[pawbench-eval] could not restrict %s", tmp)
        os.replace(tmp, _CONFIG_FILE)
    return data


def _token_hint(token: str) -> str:
    """Enough of a token to tell two of them apart, not enough to use one."""
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}…{token[-4:]}"


# ── upstream ──────────────────────────────────────────────────────────────


#: Request headers worth carrying upstream.  Everything else (cookies, the
#: console's own bearer token, hop-by-hop framing) is deliberately dropped; the
#: service's credential is added here and never travels through the browser.
_FORWARD_HEADERS = frozenset({"content-type", "accept"})
#: Response headers the browser needs to read the upstream answer as-is.
_RELAY_HEADERS = ("content-type", "content-disposition", "content-length")


class _UpstreamError(Exception):
    """The service could not be reached, as opposed to answering with an error."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


def _forward(
    method: str,
    url: str,
    *,
    token: str,
    body: Optional[bytes],
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, dict[str, str], bytes]:
    """One blocking call.  Run it in a thread so the server keeps answering."""
    outgoing = {k: v for k, v in headers.items() if k.lower() in _FORWARD_HEADERS}
    if token:
        # A presigned asset URL is its own credential; sending a bearer token
        # alongside it is at best noise and at worst a second, weaker check.
        outgoing["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=body, method=method, headers=outgoing)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        # 4xx/5xx are the service's answer, not a transport failure: their body
        # carries ``error``/``message`` and the dashboard renders it verbatim.
        return exc.code, dict(exc.headers), exc.read()
    except urllib.error.URLError as exc:
        raise _UpstreamError(str(exc.reason), code="service_unreachable") from exc
    except TimeoutError as exc:
        raise _UpstreamError(f"timed out after {timeout:.0f}s", code="service_timeout") from exc


async def _relay(method: str, path: str, request: Request) -> Response:
    base, token, _ = _effective()
    if not base:
        return _error(
            412,
            "service_not_configured",
            "还没有配置评测服务地址，先在上方「服务连接」里填一次。",
        )
    if not token:
        return _error(
            412,
            "token_missing",
            "还没有配置访问 token，先在上方「服务连接」里填一次。",
        )

    query = request.url.query
    url = f"{base}{path}" + (f"?{query}" if query else "")
    body = await request.body()
    headers = dict(request.headers)
    timeout = _TIMEOUTS.get(method, 60.0)
    try:
        status, upstream_headers, payload = await asyncio.to_thread(
            _forward,
            method,
            url,
            token=token,
            body=body or None,
            headers=headers,
            timeout=timeout,
        )
    except _UpstreamError as exc:
        return _error(
            502,
            exc.code,
            f"评测服务连不上：{exc}（地址 {base}）。检查服务是否在跑、地址是否写对。",
        )

    relayed = {
        key: value
        for key, value in upstream_headers.items()
        if key.lower() in _RELAY_HEADERS
    }
    return Response(
        content=payload,
        status_code=status,
        headers=relayed,
        media_type=relayed.get("content-type"),
    )


def _error(status: int, code: str, message: str, **details: Any) -> JSONResponse:
    """Answer in the service's own error shape, so the page has one reader."""
    payload: dict[str, Any] = {"error": code, "message": message}
    if details:
        payload["details"] = details
    return JSONResponse(status_code=status, content=payload)


# ── routes ────────────────────────────────────────────────────────────────


@router.get("/config")
async def read_config() -> dict[str, Any]:
    """What the page needs to draw the connection panel — never the token."""
    base, token, subject = _effective()
    return {
        "base_url": base,
        "has_token": bool(token),
        "token_hint": _token_hint(token),
        "subject": subject,
        "source": "file" if _CONFIG_FILE.exists() else ("env" if base or token else "none"),
    }


@router.put("/config")
async def write_config(request: Request) -> dict[str, Any]:
    """Save the connection.  An omitted ``token`` keeps the stored one.

    Omitted-means-keep is the only sane reading: the form never receives the
    token (the page is told ``has_token``), so a save that dropped it whenever
    the box was left empty would delete a working credential on every edit.
    """
    try:
        body = await request.json()
    except ValueError:
        return _error(400, "field_type_invalid", "请求体不是 JSON")
    if not isinstance(body, dict):
        return _error(400, "field_type_invalid", "请求体必须是 JSON 对象")

    patch: dict[str, Any] = {}
    if "base_url" in body:
        raw = str(body.get("base_url") or "").strip()
        if raw and not (raw.startswith("http://") or raw.startswith("https://")):
            return _error(
                400,
                "base_url_unsupported",
                "服务地址要以 http:// 或 https:// 开头",
            )
        patch["base_url"] = raw.rstrip("/")
    if "token" in body:
        patch["token"] = str(body.get("token") or "").strip()
    if "subject" in body:
        patch["subject"] = str(body.get("subject") or "").strip()

    stored = _write_file_config(patch)
    if patch.get("token"):
        # A rotated token belongs to whoever the allowlist says it does, so the
        # learned identity is no longer trustworthy.
        stored = _write_file_config({"subject": ""})
    base, token, subject = _effective()
    logger.info("[pawbench-eval] connection saved (base=%s, token=%s)", base, bool(token))
    return {
        "base_url": base,
        "has_token": bool(token),
        "token_hint": _token_hint(token),
        "subject": str(stored.get("subject") or subject),
        "source": "file",
    }


@router.post("/config/probe")
async def probe_config(request: Request) -> dict[str, Any]:
    """``/healthz`` through the same door the rest of the calls use.

    The page needs three answers and gets them in one round trip: is the base
    reachable at all, does the service recognise the token, and which service
    is this (``public_base_url`` is the one field that tells a laptop from the
    shared box when both are called "localhost" in somebody's notes).
    """
    base, token, _ = _effective()
    if not base:
        return {"configured": False, "reachable": False, "reason": "service_not_configured"}

    checked_at = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    health = await asyncio.to_thread(_health_or_none, base)
    if health is None:
        return {
            "configured": True,
            "reachable": False,
            "reason": "service_unreachable",
            "checked_at": checked_at,
            "base_url": base,
        }

    authorised = True
    if token:
        try:
            status, _, _ = await asyncio.to_thread(
                _forward,
                "GET",
                f"{base}/v1/jobs",
                token=token,
                body=None,
                headers={},
                timeout=15.0,
            )
            authorised = status not in (401, 403)
        except _UpstreamError:
            authorised = False
    return {
        "configured": True,
        "reachable": True,
        "authorised": authorised,
        "has_token": bool(token),
        "checked_at": checked_at,
        "base_url": base,
        "service": health,
    }


def _health_or_none(base: str) -> Optional[dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"{base}/healthz", timeout=10) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - "unreachable" covers every reason here
        return None


@router.post("/identity/{job_id}")
async def learn_identity(job_id: str) -> dict[str, Any]:
    """Remember who this token is, from a job the dashboard just submitted.

    The service has no "who am I" route and the token is opaque (the allowlist
    keeps only its hash), but every job carries ``submitter``.  After the first
    submission the page can therefore stop guessing whether a row is yours —
    which is what decides between a live "上移" button and a disabled one.
    """
    base, token, _ = _effective()
    if not (base and token):
        return {"subject": ""}
    try:
        status, _, payload = await asyncio.to_thread(
            _forward,
            "GET",
            f"{base}/v1/jobs/{urllib.parse.quote(job_id)}",
            token=token,
            body=None,
            headers={},
            timeout=15.0,
        )
    except _UpstreamError:
        return {"subject": ""}
    if status != 200:
        return {"subject": ""}
    try:
        submitter = str(json.loads(payload).get("submitter") or "").strip()
    except ValueError:
        return {"subject": ""}
    if submitter:
        _write_file_config({"subject": submitter})
        logger.info("[pawbench-eval] learned submitter %s", submitter)
    return {"subject": submitter}


# ── the proxy itself ──────────────────────────────────────────────────────


@router.api_route(
    "/v1/{rest:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def proxy_v1(rest: str, request: Request) -> Response:
    """Everything under ``/v1`` is the service's, including its error pages."""
    return await _relay(request.method, f"/v1/{rest}", request)


@router.get("/fetch")
async def fetch_signed(url: str) -> Response:
    """Relay one presigned URL, and only one kind of them.

    ``GET /v1/jobs/{id}/report`` answers with a link on ``public_base_url``
    rather than the bytes (a zip is 64 MB of somebody else's files, and the
    service will not stream that through a request handler).  The browser could
    open that link itself — unless its host cannot reach the service's public
    address, which is exactly the case this plugin exists for: QwenPaw runs on a
    laptop behind one address, the service on another.

    Guarded to the configured origin: an endpoint that fetches any URL a caller
    names is an SSRF proxy, and the signature in the query string is the only
    thing that makes this one safe to forward.
    """
    base, _, _ = _effective()
    if not base:
        return _error(412, "service_not_configured", "还没有配置评测服务地址。")
    target = urllib.parse.urlsplit(url)
    expected = urllib.parse.urlsplit(base)
    if (target.scheme, target.netloc) != (expected.scheme, expected.netloc):
        return _error(
            400,
            "fetch_origin_refused",
            f"只能转发 {expected.scheme}://{expected.netloc} 下的地址",
        )
    try:
        status, headers, payload = await asyncio.to_thread(
            _forward,
            "GET",
            url,
            token="",
            body=None,
            headers={},
            timeout=120.0,
        )
    except _UpstreamError as exc:
        return _error(502, exc.code, f"下载失败：{exc}")
    relayed = {
        key: value for key, value in headers.items() if key.lower() in _RELAY_HEADERS
    }
    return Response(
        content=payload,
        status_code=status,
        headers=relayed,
        media_type=relayed.get("content-type"),
    )


# ── app wiring ────────────────────────────────────────────────────────────

app = PawApp(name="PawBench Eval", app_id="pawbench-eval")
app.include_router(router)
app.skill_provider(
    skills_dir=_SKILLS_DIR,
    enabled_by_default=True,
    channels=["all"],
)


@app.on_launch
async def check_service_on_launch() -> None:
    """Say something once, at the moment the page opens, if the service is down.

    A dashboard whose every request answers 502 and whose log is empty sends
    the reader to the wrong file.  One line here names the address that failed.
    """
    base, token, _ = _effective()
    if not base:
        logger.info("[pawbench-eval] no service configured yet")
        return
    health = await asyncio.to_thread(_health_or_none, base)
    if health is None:
        logger.warning("[pawbench-eval] evaluation service unreachable at %s", base)
        return
    logger.info(
        "[pawbench-eval] evaluation service ready at %s (token %s)",
        base,
        "configured" if token else "MISSING",
    )


#: What the plugin loader looks for.
plugin = app
