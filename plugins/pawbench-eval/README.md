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
**服务连接**:

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

- **提交评测** — ACP address, a mixed selector (whole categories + individual
  datasets), and an inline panel that resolves the selection to a task count as
  you pick.  Window: immediate / night / custom range, with the reader's zone and
  the service's zone on separate lines (the seven-hour mistake this exists to
  prevent).
- **队列** — every job on the service, whoever submitted it.  Reordering is by
  buttons (队首 / 上移 / 下移 / 队尾), disabled with a reason when the row is
  running or belongs to somebody else; cancel and detail sit beside them.
- **结果** — finished jobs expand to scores and per-capability / per-scenario
  slices.
- **任务详情** — one modal, three levels: job overview → per-task table →
  one task's grading, artifacts and paged transcript.  Two tiers: `shared` for
  everyone, and a `完整版` switch that carries the warning line the design asks
  for.
- **数据集** — list, new builtin view, custom package upload, category
  management.  A delete button appears only on rows you own.

## Notes for whoever edits this

Third-party dependencies, if this plugin ever needs any, go in
`requirements.txt` at the **plugin root** -- the installer reads
`~/.qwenpaw/plugins/pawbench-eval/requirements.txt` and never looks inside
`backend/`.  Nothing is needed today: the backend uses only the standard library
and the FastAPI that QwenPaw already provides.

`ui/index.js` must stay a single file.  The host fetches it, wraps it in a Blob
and `import()`s it, so a relative import resolves against the blob URL and fails
on the machine that matters.
