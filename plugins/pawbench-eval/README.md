# PawBench evaluation plugin

Two things in one plugin: a dashboard page in the QwenPaw console, and a skill
(`pawbench-datasets`) in every workspace.  Both talk to the PawBench evaluation
service; neither is useful without one running.

Feature documents: `pal_sdd/feat_acp_remote_eval/` (prd / design / test /
acceptance).  The user-facing manual, in Chinese, is
`pal_sdd/feat_acp_remote_eval/manual_acp_remote_eval.md` -- send that one to
whoever has to click through the page; this file is for whoever edits it.

## Install

```bash
qwenpaw plugin validate plugins/pawbench-eval
qwenpaw plugin install  plugins/pawbench-eval
```

Re-run with `--force` after pulling a change.  `install` **copies** the directory
into `~/.qwenpaw/plugins/pawbench-eval` (no symlink), so an edit here reaches
nobody until somebody installs again -- and nobody is notified automatically.
Whoever changes the plugin says so in the channel the team already uses.

The skill is gated on the MCP server: until `pawbench-eval` is configured in
QwenPaw the skill does not appear in the skill list.  QwenPaw has no
`register_mcp*` hook, so that step is manual (see `website/public/docs/mcp.en.md`
in the QwenPaw checkout): the endpoint is `<service>/mcp` and it needs
`Authorization: Bearer <token>`.

## First run

Open **PawBench 评测** in the sidebar (route `/apps/pawbench-eval`), then
**配置** in the left rail:

| Field | What goes in it |
|---|---|
| 评测服务地址 | the service's `public_base_url`, e.g. `http://127.0.0.1:8471` |
| 访问 token | a token issued by `service.auth add-subject`; pasted once, never shown again |
| 我的身份 | optional. The submitter name this token belongs to; filled in automatically after the first submission |

The connection is saved to `<plugin>/data/config.json` beside the installed
copy.  Two environment variables can stand in for it — `PAWBENCH_EVAL_BASE_URL`
and `PAWBENCH_EVAL_TOKEN` — for a machine nobody wants to click through (CI, a
demo box).  The saved form wins when both are set, because it is the one with a
save button.

**The token never reaches the browser.**  The page calls this plugin's own
`/api/pawbench-eval/v1/...`, and the backend adds the credential while
forwarding.  That is the whole reason for the proxy: otherwise every token
holder pastes the same secret into two places and a browser devtools session
hands it to whoever is screen-sharing.

## What the page does

Three modules behind a fixed rail.  Submitting a run, curating datasets and
pointing the board at a service are three different jobs done at different
times; stacking them on one page meant scrolling past a form to read a score.

- **评测 (jobs)** — the list is the landing page: three headline numbers (running
  / waiting / finished, the last carrying the mean) over one row per submission, each row
  carrying its task progress and its mean score, taken from one grouped query
  rather than a detail request per line.  **＋ 新建评测** opens the submission
  form as a modal: ACP address, product, purpose, a mixed selector (whole
  categories + individual datasets) that resolves to a task count as you pick,
  and the window (immediate / night / custom range) with the reader's zone and
  the service's zone on separate lines — the seven-hour mistake this exists to
  prevent.
- **报告 (report)** — a full page, not a modal, because it now carries the task
  text.  Header: purpose, status, copyable job id, product, submitter.  Tabs:
  **总览** (score dial, slices, sources, fingerprint), **题目**
  (searchable/filterable task table → one task's prompt, criteria, artifacts and
  timeline), **导出** (report formats and download).
- **数据集 (datasets)** — list, new builtin view, custom package upload, category
  management.  A delete button appears only on rows you own.
- **配置 (settings)** — service address, token, identity, probe result, and the
  defaults a report opens with.  The token is write-only here: the page is told
  `has_token`, never the value.

### What a report shows, and why

A score nobody can trace back to a run is a number, not a measurement.  Each
task entry therefore carries two ids, and the exported file carries them too:

| id | whose | what it is for |
|---|---|---|
| `trace_id` | ours, 16 hex chars per attempt | `grep <trace_id>` on the service log: session open, manifest issued, the reason it failed |
| `session_id` | the agent's own handle | the agent's logs, so both sides can be shown to describe the same conversation |

`session_id` is minted *by us, in the shape the agent uses*
(`1795156778446-y2r8j2a`: epoch millis, a hyphen, seven lowercase base-36
characters) and then handed to the agent through `session/load`, so the id in
the report is the one the agent files its own history under.  An agent that
declares `loadSession` adopts it and every later update is routed by it; an
agent that cannot keeps the id it minted itself, which is still the right id to
grep — it is just not the one we chose.  Asking the agent to adopt our id is what
makes "open this session in your console" a working instruction rather than a
translation exercise.

Both are printed next to the score rather than tucked behind a switch: the
report is the document a reader uses to tell whoever owns the agent which run it
was, and an id you have to change a setting to see is an id that goes unchecked.
A retry gets a new `trace_id`, which is the point — two attempts of the same task
never share log lines.  Rows written before the columns existed read as `—`.

The task's own prompt is in the report for the same reason: a reader who cannot
see the question cannot argue with the answer, and sending them to another
system to find it is how a report stops being read.

The files follow the same rule, so both of them can be opened from the task
view: the attachments the task handed the agent (`…/attachments`), and what the
agent wrote back (`…/artifacts`).  Each has a `preview` twin that answers "what
is inside" with text or a data URL, capped at 256 KB / 2 MB -- an artifact can
be 64 MB, and the point of the route is that the bytes never cross the wire in
full.  The service, not the browser, decides whether a file is text: a `.txt`
that is really a zip is named a binary rather than decoded into mojibake.

The attachment route only serves a path the task *declares*.  The session
directory beside an attempt also holds whatever the agent wrote there, so "any
path under it" would be a file browser over somebody else's working directory.

## Notes for whoever edits this

Third-party dependencies, if this plugin ever needs any, go in
`requirements.txt` at the **plugin root** -- the installer reads
`~/.qwenpaw/plugins/pawbench-eval/requirements.txt` and never looks inside
`backend/`.  Nothing is needed today: the backend uses only the standard library
and the FastAPI that QwenPaw already provides.

`ui/index.js` is the file the host loads, and it must stay a single file.  The
host fetches it, wraps it in a Blob and `import()`s it, so a relative import
resolves against the blob URL and fails on the machine that matters — and a
bare specifier (`antd`, `react`) has no import map to resolve against at all.
It is therefore **built**, not hand-written:

```
ui/src/           what you edit — React + antd sources, one module per screen
ui/build.mjs      esbuild: JSX -> the host's createElement, CSS -> a string
ui/index.js       the artifact.  Committed, because `install` copies the
                  directory and never runs npm.
```

```bash
cd ui && npm install          # once
npm run build                 # writes index.js
npm run typecheck             # tsc --noEmit
```

Two rules the build encodes rather than documents.  JSX compiles to
`window.QwenPaw.host.React.createElement` through `src/host/jsx.ts`, so no React
copy of ours can ever be the one that rendered a component of theirs.  And
antd is *destructured from the host* (`src/host/antd.ts`), not bundled: two antd
instances mean two `ConfigProvider`s and a modal that renders in the wrong
theme.

`src/designsys/` holds the team's token and component stylesheets verbatim
(`.qoder/skills/designsys-full`).  The page sets `data-theme` on its own root
from the host's `colorBgBase`, then reads the resolved custom properties back
out of the CSS and hands them to `ConfigProvider` — one source of colour, so
"no literal colours anywhere except `designsys/`" is enforced by there being
nowhere else to get a colour from.  `tests/cpd/acp_remote_eval/test_plugin.py`
scans `ui/src` for hex and `rgb()` literals to keep it that way.
