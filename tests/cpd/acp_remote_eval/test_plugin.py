# -*- coding: utf-8 -*-
"""The plugin's contracts with QwenPaw, checked against the files we ship.

The plugin lives in this repository instead of QwenPaw's plugin directory
(design §12, D20), so nothing on the host's side fails when our manifest, the
``register(api)`` entry or the skill's MCP gate drifts away from what the loader
parses.  The failure is silent and remote: somebody installs the plugin and the
skill simply is not in the list, or the backend imports and registers nothing.

These cases read exactly what the host reads -- ``plugin.json``, the SKILL.md
front matter, the frontend module -- and the files this repository owns.  The
tool names quoted by the skill are pinned to ``mcp/server.py`` because that list
is written by hand: rename a tool on the server and the skill keeps telling an
agent to call something that no longer exists, which fails as a confused agent
rather than as a red suite.

The backend is imported here, which means standing in for ``qwenpaw.pawapp``:
this suite runs without QwenPaw installed, and importing the real one would
test QwenPaw rather than our use of it.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest
import yaml

from pawbench.cpd.acp_remote_eval.service.datasets import validate_package

ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = ROOT / "plugins" / "pawbench-eval"
SKILLS_DIR = PLUGIN_DIR / "skills"
SERVER = ROOT / "pawbench" / "cpd" / "acp_remote_eval" / "mcp" / "server.py"
SERVICE_API = ROOT / "pawbench" / "cpd" / "acp_remote_eval" / "service" / "api.py"
UI_DIR = PLUGIN_DIR / "ui"
UI_SRC = UI_DIR / "src"
UI_BUNDLE = UI_DIR / "index.js"
BACKEND = PLUGIN_DIR / "backend" / "main.py"

# PluginType in QwenPaw src/qwenpaw/plugins/architecture.py:22, spelled out
# because this suite runs without QwenPaw installed.  The point is to notice a
# manifest naming a type the host does not have, not to import the enum.
PLUGIN_TYPES = frozenset(
    {"tool", "provider", "hook", "command", "channel", "hub", "memory",
     "frontend", "app", "general"}
)

#: What the dashboard calls, as the service must answer it.  Both halves are
#: checked: the path has to exist in ``service/api.py`` and the literal has to
#: still be in ``ui/index.js``, so a route rename on either side is red here
#: instead of being a 404 somebody reads off a screenshot.
DASHBOARD_ENDPOINTS = [
    ("GET", "/v1/jobs", "/v1/jobs"),
    ("POST", "/v1/jobs", "/v1/jobs"),
    ("GET", "/v1/jobs/job-x", "/v1/jobs/"),
    ("PATCH", "/v1/jobs/job-x", "/v1/jobs/"),
    ("POST", "/v1/jobs/job-x/cancel", "/cancel"),
    ("GET", "/v1/jobs/job-x/detail", "/detail"),
    ("GET", "/v1/jobs/job-x/tasks/t1/detail", "/tasks/"),
    ("GET", "/v1/jobs/job-x/results", "/results"),
    ("GET", "/v1/jobs/job-x/transcript", "/transcript?task_id="),
    ("GET", "/v1/jobs/job-x/report", "/report?format="),
    ("GET", "/v1/datasets", "/v1/datasets"),
    ("POST", "/v1/datasets", "/v1/datasets"),
    ("DELETE", "/v1/datasets/ds-1", "/v1/datasets/"),
    ("POST", "/v1/datasets/resolve", "/v1/datasets/resolve"),
    ("POST", "/v1/datasets/packages", "/v1/datasets/packages?"),
    ("GET", "/v1/dataset-categories", "/v1/dataset-categories"),
    ("POST", "/v1/dataset-categories", "/v1/dataset-categories"),
    ("DELETE", "/v1/dataset-categories/cat-1", "/v1/dataset-categories/"),
]


# ── reading what the host reads ───────────────────────────────────────────


def _dashboard_source() -> str:
    """Every frontend source file, joined, for the endpoint-fragment checks."""
    files = [
        path
        for path in sorted(UI_SRC.rglob("*"))
        if path.is_file() and path.suffix in {".ts", ".tsx"}
    ]
    assert files, f"no frontend source under {UI_SRC}"
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def _manifest() -> dict:
    return json.loads((PLUGIN_DIR / "plugin.json").read_text(encoding="utf-8"))


def _skill_dir() -> Path:
    dirs = [path for path in sorted(SKILLS_DIR.iterdir()) if (path / "SKILL.md").is_file()]
    assert len(dirs) == 1, f"expected one skill, found {[path.name for path in dirs]}"
    return dirs[0]


def _front_matter(skill_md: Path) -> dict:
    text = skill_md.read_text(encoding="utf-8")
    header = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert header is not None, f"{skill_md} carries no front matter"
    return yaml.safe_load(header.group(1))


def _server_tool_names() -> set[str]:
    source = SERVER.read_text(encoding="utf-8")
    return set(re.findall(r"async def (pawbench_[a-z0-9_]+)\(", source))


def _service_routes() -> list[tuple[str, str]]:
    """``(METHOD, path pattern)`` for every control-plane route the service has."""
    source = SERVICE_API.read_text(encoding="utf-8")
    routes: list[tuple[str, str]] = []
    for match in re.finditer(r'@app\.(get|post|put|patch|delete)\(\s*"([^"]+)"', source):
        routes.append((match.group(1).upper(), match.group(2)))
    return routes


def _pattern_matches(pattern: str, concrete: str) -> bool:
    """``/v1/jobs/{job_id}/detail`` matches ``/v1/jobs/job-x/detail``."""
    parts = re.split(r"(\{[^}]+\})", pattern)
    regex = "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts)
    return re.fullmatch(regex, concrete) is not None


# ── standing in for QwenPaw ───────────────────────────────────────────────


class _FakePawApp:
    """Just enough of ``qwenpaw.pawapp.PawApp`` to see what the backend asks for."""

    def __init__(self, name: str = "", *, app_id: str = "") -> None:
        self.name = name
        self.app_id = app_id
        self.routers: list[Any] = []
        self.skill_providers: list[dict[str, Any]] = []
        self.lifecycle: dict[str, Any] = {}

    def include_router(self, router: Any, **_: Any) -> None:
        self.routers.append(router)

    def skill_provider(self, skills_dir: Path | str, **kwargs: Any) -> None:
        self.skill_providers.append({"skills_dir": Path(skills_dir), **kwargs})

    def on_launch(self, func: Any) -> Any:
        self.lifecycle["launch"] = func
        return func

    def on_terminate(self, func: Any) -> Any:
        self.lifecycle["terminate"] = func
        return func


def _load_backend() -> Any:
    """Import ``backend/main.py`` with ``qwenpaw.pawapp`` replaced by the stub."""
    package = types.ModuleType("qwenpaw")
    pawapp = types.ModuleType("qwenpaw.pawapp")
    pawapp.PawApp = _FakePawApp  # type: ignore[attr-defined]
    pawapp.get_ctx = lambda: None  # type: ignore[attr-defined]
    package.pawapp = pawapp  # type: ignore[attr-defined]
    saved = {name: sys.modules.get(name) for name in ("qwenpaw", "qwenpaw.pawapp")}
    sys.modules["qwenpaw"] = package
    sys.modules["qwenpaw.pawapp"] = pawapp
    try:
        spec = importlib.util.spec_from_file_location("pawbench_eval_backend", BACKEND)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous


# ── manifest ──────────────────────────────────────────────────────────────


def test_the_manifest_answers_what_the_installer_asks() -> None:
    manifest = _manifest()
    assert manifest["id"] == PLUGIN_DIR.name, "the install target is the directory name"
    assert manifest["type"] in PLUGIN_TYPES
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["qwenpaw_version"]["min"]
    for entry in ("backend", "frontend"):
        assert (PLUGIN_DIR / manifest["entry"][entry]).is_file(), f"entry.{entry} is missing"
    assert manifest["meta"]["pawapp"]["entry_page"] == "/apps/" + manifest["id"]


def test_the_dependency_list_sits_where_the_installer_reads_it() -> None:
    """plugin_commands.py reads ``PLUGINS_DIR/<id>/requirements.txt`` only."""
    assert (PLUGIN_DIR / "requirements.txt").is_file()
    assert not (PLUGIN_DIR / "backend" / "requirements.txt").exists()


def test_the_frontend_registers_the_page_the_manifest_advertises() -> None:
    """A ``pawapp.entry_page`` nobody registers is a menu item that 404s."""
    manifest = _manifest()
    source = (UI_SRC / "index.tsx").read_text(encoding="utf-8")
    registered = re.search(r'registerRoutes\(\s*"([^"]+)"', source)
    assert registered is not None, "the module registers no routes at all"
    assert registered.group(1) == manifest["id"]
    paths = re.findall(r'path:\s*"([^"]+)"', source)
    assert manifest["meta"]["pawapp"]["entry_page"] in paths, paths


# ── backend ───────────────────────────────────────────────────────────────


def test_the_backend_registers_the_skills_directory_next_to_itself() -> None:
    module = _load_backend()
    app = module.plugin
    assert isinstance(app, _FakePawApp)
    assert app.app_id == PLUGIN_DIR.name
    assert len(app.skill_providers) == 1
    provider = app.skill_providers[0]
    assert provider["skills_dir"].resolve() == SKILLS_DIR.resolve()
    assert provider["channels"] == ["all"]
    assert provider["enabled_by_default"] is True
    assert "launch" in app.lifecycle, "nothing probes the service when the page opens"


def test_the_backend_anchors_on_its_own_location_only() -> None:
    """``install`` is a copytree into ``~/.qwenpaw/plugins/<id>``, not a symlink.

    Anything derived from the repository path resolves to nothing on the target
    machine, and nothing reports it: the plugin loads and registers an empty
    skills directory.
    """
    source = BACKEND.read_text(encoding="utf-8")
    assert "__file__" in source
    assert "plugins/pawbench-eval" not in source
    assert "CPDPawBench" not in source


def test_the_backend_never_hides_its_routes_behind_a_second_prefix() -> None:
    """The page calls ``/api/pawbench-eval/v1/...``; PawApp already adds that.

    A route written ``/pawbench-eval/v1/...`` would be mounted at
    ``/api/pawbench-eval/pawbench-eval/v1/...`` and answer 404 on every call.
    """
    module = _load_backend()
    paths = sorted(
        route.path for router in module.plugin.routers for route in router.routes
    )
    assert paths, "the backend registers no routes"
    assert all(path.startswith(("/v1", "/config", "/identity", "/fetch")) for path in paths)
    assert "/v1/{rest:path}" in paths


def test_runtime_state_is_kept_out_of_the_installed_copy() -> None:
    """``data/config.json`` holds a bearer token, and ``install`` copies the tree.

    A committed one would hand the author's credential to everybody who installs
    from this checkout, so the guard is the ignore file, not a habit.
    """
    ignore = (PLUGIN_DIR / ".gitignore").read_text(encoding="utf-8")
    ignored = {
        line.strip().rstrip("/")
        for line in ignore.splitlines()
        if line.strip() and not line.startswith("#")
    }
    assert "data" in ignored, ignored
    assert "__pycache__" in ignored, ignored


# ── dashboard ⇄ service contract ───────────────────────────────────────────


def test_every_endpoint_the_dashboard_calls_exists_on_the_service() -> None:
    routes = _service_routes()
    assert routes, "no route was found in service/api.py"
    missing = [
        (method, path)
        for method, path, _ in DASHBOARD_ENDPOINTS
        if not any(
            route_method == method and _pattern_matches(route_path, path)
            for route_method, route_path in routes
        )
    ]
    assert not missing, missing


def test_the_dashboard_still_calls_every_endpoint_it_promises() -> None:
    source = _dashboard_source()
    missing = [fragment for _, _, fragment in DASHBOARD_ENDPOINTS if fragment not in source]
    assert not missing, missing


def test_the_shipped_bundle_is_self_contained() -> None:
    """``usePluginLoader`` wraps the file in a Blob and ``import()``s it.

    A module specifier — bare or relative — resolves against the blob URL and
    fails on the host that matters, and there is no import map to save it.  The
    bundle therefore has to carry React and antd access, CSS injection and every
    module of its own; only ``window.QwenPaw.host`` may come from outside.
    """
    assert UI_BUNDLE.is_file(), "ui/index.js is missing: run `npm run build` in ui/"
    source = UI_BUNDLE.read_text(encoding="utf-8")
    assert not re.search(r"^\s*import\s", source, re.MULTILINE), "the bundle imports a module"
    assert not re.search(r'\bfrom\s*["\']', source), "the bundle resolves a specifier at run time"
    assert "window.QwenPaw" in source
    assert "registerRoutes" in source
    # One marker per module, so a stale bundle (built before a module existed)
    # fails here rather than as a blank panel on somebody's screen.
    for marker in ("pbe-root", "新建评测", "数据集", "配置", "session_id"):
        assert marker in source, marker


def test_the_frontend_is_built_from_readable_sources() -> None:
    """The bundle is an artifact; the thing to review is ``ui/src``.

    Pinning the arrangement keeps a future edit from hand-patching the 170 KB
    build output, which would be invisible in review and lost on the next build.
    """
    package = json.loads((UI_DIR / "package.json").read_text(encoding="utf-8"))
    assert "build" in package["scripts"]
    assert (UI_DIR / "build.mjs").is_file()
    modules = sorted(path.name for path in UI_SRC.glob("*.tsx"))
    assert {"index.tsx", "shell.tsx", "theme.tsx"} <= set(modules), modules
    assert (UI_SRC / "modules").is_dir()
    assert (UI_SRC / "designsys" / "colors_and_type.css").is_file()


def test_the_dashboard_takes_no_colour_literals() -> None:
    """DesignSys v1: colour comes from the token set, never from a hex value.

    Two exemptions, both deliberate: ``src/designsys/`` *is* the token source,
    so its hex values are the origin rather than a violation, and the produced
    bundle is not read at all.  Light and dark are one code path because the
    same semantic token names are used under both themes.
    """
    sources = [
        path
        for path in sorted(UI_SRC.rglob("*"))
        if path.is_file()
        and path.suffix in {".ts", ".tsx", ".css"}
        and "designsys" not in path.parts
    ]
    assert sources
    offenders: list[str] = []
    for path in sources:
        text = path.read_text(encoding="utf-8")
        if re.search(r"#[0-9a-fA-F]{3,8}\b", text) or re.search(r"\brgba?\(", text):
            offenders.append(str(path.relative_to(UI_SRC)))
    assert not offenders, offenders
    assert "useToken" in (UI_SRC / "theme.tsx").read_text(encoding="utf-8")


# ── skill ─────────────────────────────────────────────────────────────────


def test_the_skill_is_gated_on_the_server_the_service_mounts() -> None:
    skill_dir = _skill_dir()
    front = _front_matter(skill_dir / "SKILL.md")
    # The host keys a workspace skill by its directory name.
    assert front["name"] == skill_dir.name
    assert front["description"].strip()
    gate = front["metadata"]["qwenpaw"]["requires"]["mcp"]
    mounted = re.search(r'FastMCP\(\s*"([^"]+)"', SERVER.read_text(encoding="utf-8"))
    assert mounted is not None, "the server is constructed without a name"
    assert gate == [mounted.group(1)], "an unmet gate hides the skill without an error"


def test_every_tool_the_skill_names_exists_on_the_server() -> None:
    named = set()
    for path in sorted(SKILLS_DIR.rglob("*.md")):
        named |= set(re.findall(r"pawbench_[a-z0-9_]+", path.read_text(encoding="utf-8")))
    assert named, "the skill names no tool at all, which makes this case vacuous"
    assert named <= _server_tool_names(), sorted(named - _server_tool_names())


def test_the_task_skeleton_is_a_package_the_service_accepts(tmp_path: Path) -> None:
    skeleton = _skill_dir() / "templates" / "task.md"
    package = tmp_path / "package"
    (package / "tasks").mkdir(parents=True)
    task_md = package / "tasks" / "skeleton.md"
    task_md.write_text(skeleton.read_text(encoding="utf-8"), encoding="utf-8")
    result = validate_package(package)
    assert result.ok, result.problems
    assert len(result.task_ids) == 1
    # TaskLoader._extract_grading_criteria reads "- [ ] ..." and nothing else, so
    # a skeleton with plain bullets grades every task with an empty rubric.
    text = task_md.read_text(encoding="utf-8")
    criteria = text.split("## Grading Criteria", 1)[1]
    assert re.search(r"^- \[ \] .+", criteria, re.MULTILINE), criteria


# ── the proxy, against an upstream that records what it received ───────────

SERVICE_TOKEN = "service-side-token"


class _Upstream:
    """A recording stand-in for the evaluation service."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        handler = self._handler()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        upstream = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:  # silence the test output
                pass

            def _record(self) -> bytes:
                length = int(self.headers.get("content-length") or 0)
                body = self.rfile.read(length) if length else b""
                upstream.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("authorization"),
                        "content_type": self.headers.get("content-type"),
                        "body": body,
                    }
                )
                return body

            def _answer(self) -> None:
                self._record()
                if "refuse" in self.path:
                    body = {"error": "reorder_field_unknown", "message": "no"}
                    payload = json.dumps(body).encode()
                    self.send_response(400)
                elif self.path.startswith("/healthz"):
                    payload = json.dumps(
                        {"ok": True, "public_base_url": upstream.base_url},
                    ).encode()
                    self.send_response(200)
                else:
                    payload = json.dumps({"path": self.path}).encode()
                    self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            do_GET = _answer
            do_POST = _answer
            do_PATCH = _answer
            do_PUT = _answer
            do_DELETE = _answer

        return Handler

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> "_Upstream":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The backend with its config file redirected into the test's tmp_path."""
    pytest.importorskip("fastapi", reason="fastapi is declared in the cpd requirements")
    module = _load_backend()
    monkeypatch.setattr(module, "_CONFIG_FILE", tmp_path / "data" / "config.json")
    monkeypatch.delenv(module._ENV_BASE, raising=False)
    monkeypatch.delenv(module._ENV_TOKEN, raising=False)
    yield module


@pytest.fixture()
def client(backend: Any) -> Iterator[Any]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(backend.plugin.routers[0], prefix="/pawbench-eval")
    with TestClient(app) as test_client:
        yield test_client


def _configure(client: Any, base_url: str) -> None:
    response = client.put(
        "/pawbench-eval/config",
        json={"base_url": base_url, "token": SERVICE_TOKEN},
    )
    assert response.status_code == 200, response.text


def test_an_unconfigured_proxy_names_the_reason(client: Any) -> None:
    response = client.get("/pawbench-eval/v1/jobs")
    assert response.status_code == 412, response.text
    assert response.json()["error"] == "service_not_configured"


def test_the_proxy_keeps_the_path_the_query_and_the_body(client: Any) -> None:
    with _Upstream() as upstream:
        _configure(client, upstream.base_url)
        response = client.get("/pawbench-eval/v1/jobs?status=queued&status=running&limit=5")
        assert response.status_code == 200
        sent = upstream.requests[-1]
        assert sent["path"] == "/v1/jobs?status=queued&status=running&limit=5"
        assert sent["method"] == "GET"

        response = client.post(
            "/pawbench-eval/v1/datasets/resolve",
            json={"selector": {"datasets": ["pilot_v1"], "categories": []}},
        )
        assert response.status_code == 200
        sent = upstream.requests[-1]
        assert sent["method"] == "POST"
        assert sent["path"] == "/v1/datasets/resolve"
        assert json.loads(sent["body"])["selector"]["datasets"] == ["pilot_v1"]
        assert sent["content_type"] == "application/json"


def test_the_service_token_is_added_and_the_console_token_is_not_forwarded(client: Any) -> None:
    """The point of the proxy: the service credential never reaches the browser,
    and the console's own bearer token is not handed to a third party."""
    with _Upstream() as upstream:
        _configure(client, upstream.base_url)
        client.get(
            "/pawbench-eval/v1/jobs",
            headers={"Authorization": "Bearer console-session-token"},
        )
        assert upstream.requests[-1]["authorization"] == f"Bearer {SERVICE_TOKEN}"


def test_an_upstream_refusal_arrives_with_its_status_and_its_code(client: Any) -> None:
    with _Upstream() as upstream:
        _configure(client, upstream.base_url)
        response = client.patch("/pawbench-eval/v1/jobs/job-1/refuse", json={"nonsense": 1})
        assert response.status_code == 400
        assert response.json()["error"] == "reorder_field_unknown"


def test_an_unreachable_service_answers_502_rather_than_500(client: Any) -> None:
    _configure(client, "http://127.0.0.1:9")
    response = client.get("/pawbench-eval/v1/jobs")
    assert response.status_code == 502
    assert response.json()["error"] == "service_unreachable"


def test_the_config_route_never_hands_the_token_back(client: Any) -> None:
    with _Upstream() as upstream:
        _configure(client, upstream.base_url)
        body = client.get("/pawbench-eval/config").json()
        assert SERVICE_TOKEN not in json.dumps(body)
        assert body["has_token"] is True
        assert body["token_hint"].endswith(SERVICE_TOKEN[-4:])

        # An edit that leaves the token box empty must keep the credential.
        again = client.put("/pawbench-eval/config", json={"base_url": upstream.base_url})
        assert again.status_code == 200
        assert client.get("/pawbench-eval/config").json()["has_token"] is True


def test_the_saved_token_is_not_world_readable(client: Any, backend: Any) -> None:
    """The token has to live somewhere; it must not be readable by every account.

    The plugin directory sits in a home directory, and ``~`` is not a permission
    boundary on a shared machine.
    """
    import os
    import stat

    with _Upstream() as upstream:
        _configure(client, upstream.base_url)
        mode = stat.S_IMODE(os.stat(backend._CONFIG_FILE).st_mode)
        assert mode == 0o600, oct(mode)


def test_probing_reports_both_reachability_and_authorisation(client: Any) -> None:
    with _Upstream() as upstream:
        _configure(client, upstream.base_url)
        body = client.post("/pawbench-eval/config/probe").json()
        assert body["reachable"] is True
        assert body["authorised"] is True
        assert body["service"]["public_base_url"] == upstream.base_url

    _configure(client, "http://127.0.0.1:9")
    body = client.post("/pawbench-eval/config/probe").json()
    assert body["reachable"] is False


def test_fetch_relays_only_the_configured_origin(client: Any) -> None:
    """``/fetch`` exists for presigned report links; an open relay would be SSRF."""
    with _Upstream() as upstream:
        _configure(client, upstream.base_url)
        inside = client.get(
            "/pawbench-eval/fetch",
            params={"url": upstream.base_url + "/v1/reports/x.md?sig=abc"},
        )
        assert inside.status_code == 200, inside.text
        assert upstream.requests[-1]["path"] == "/v1/reports/x.md?sig=abc"
        # A presigned URL is its own credential; no bearer token alongside it.
        assert upstream.requests[-1]["authorization"] is None

        outside = client.get(
            "/pawbench-eval/fetch",
            params={"url": "http://169.254.169.254/latest/meta-data/"},
        )
        assert outside.status_code == 400
        assert outside.json()["error"] == "fetch_origin_refused"
