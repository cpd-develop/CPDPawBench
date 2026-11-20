# ACP remote eval

Evaluates an agent that runs **somewhere else**.  The subject is that agent plus
its own harness, model and tools; this package is the service that hands it a
task's fixtures over HTTP, collects the files it produced, and rebuilds a
workspace the grader can read.  Nothing here imports the benchmark CLI, and
`run_bench.py` does not import this package -- an installation that only runs
the local benchmark gains nothing from it.

## Install

Python 3.11+ (developed and tested on 3.12), on top of the repo's own
`requirements.txt`:

```bash
pip install -r pawbench/cpd/acp_remote_eval/requirements.txt
```

The HTTP data plane needs `fastapi` + `uvicorn`; the ACP conversation needs
`agent-client-protocol`.  To evaluate an agent that answers at a URL instead of
a command we spawn, add the SDK's transport extra:

```bash
pip install 'agent-client-protocol[http]'
```

## Run the tests

```bash
python -m pytest tests/cpd/acp_remote_eval -q
```

The end-to-end file (`test_runner_e2e.py`) starts a real uvicorn on a free
localhost port and spawns `tests/cpd/acp_remote_eval/tools/fake_acp_agent.py` as
a separate process that speaks ACP over stdio, so the process boundary, the URL
signing and the stderr pipe are exercised rather than mocked.

## Run the service

```bash
cp pawbench/cpd/acp_remote_eval/service/config.example.yaml \
   pawbench/cpd/acp_remote_eval/service/config.yaml
# then edit public_base_url / bind / builtin_dir, and mint the first token:
python -m pawbench.cpd.acp_remote_eval.service.auth \
    --allowlist pawbench/cpd/acp_remote_eval/service/runtime/allowlist.yaml \
    add-subject --subject <you>
python -m pawbench.cpd.acp_remote_eval --config pawbench/cpd/acp_remote_eval/service/config.yaml
```

`config.yaml` and everything under `service/runtime/` (the sqlite state, the
allowlist, uploaded artifacts, custom datasets) are git-ignored: they are a
scheduling record, not a deliverable.  `--config` also reads
`$PAWBENCH_EVAL_CONFIG`, and falls back to `service/config.yaml` beside the
package.  Omitting `state_db` / `custom_dir` / `exchange_dir` / `builtin_dir`
gives the same four locations the example shows, because relative paths anchor
to the directory holding the config file -- so a first config that sets nothing
but `public_base_url` still keeps its state database out of the package.  Two
more rules (`service/service/`, `service/data/`) ignore the shapes a hand-written
relative path could produce; nothing the defaults generate lands there.

One process carries both halves of the design: the HTTP data plane the agent
PUTs its answers to, and the scheduler tick that decides when to run a job.  On
startup it settles any job left `running` by a dead process -- `failed` with
reason `recovered`, its unreached tasks `skipped(service_restarted)` -- instead
of resuming it, because the dead attempt's workspace is still on disk and a
second run would have half-written files scored as its own output.

## Submit a job

```bash
export PAWBENCH_EVAL_SERVER=http://127.0.0.1:8712
export PAWBENCH_EVAL_TOKEN=<what add-subject printed once>
python -m pawbench.cpd.acp_remote_eval.cli submit \
    --acp-url http://127.0.0.1:8080/acp --product QwenPaw --purpose nightly \
    --categories email --env model=qwen3-max --env build=2026.11
```

## Evaluate an agent that only speaks stdio

The service reaches subjects over streamable HTTP only -- a job row that
carried a command would let one submitter run anything on the service host.
Most coding agents, QwenPaw included, speak ACP over stdio and nothing else, so
this package ships the seam for them:

```bash
# The bridge needs the streamable-HTTP extra, which this package does not
# require: a deployment that only evaluates agents it launches itself should not
# pay for it.  Install it into the environment that runs the service.
pip install 'agent-client-protocol[http]' uvicorn

python -m pawbench.cpd.acp_remote_eval.bridge \
    --command "/path/to/QwenPaw/venv_312/bin/qwenpaw acp" \
    --port 8472
# then submit with --acp-url http://127.0.0.1:8472/acp
```

**Do not install it into the subject agent's own venv.** The `http` extra first
appears in `agent-client-protocol` 1.0, while a subject may pin something older
-- QwenPaw pins `<0.11.0`, so that venv holds 0.10.1, `pip install
'agent-client-protocol[http]'` only prints `does not provide the extra 'http'`
and adds nothing, and `acp.http` stays absent. The two sides meet on the wire,
not in a shared site-packages: the bridge speaks HTTP with its own SDK while the
agent it spawned keeps its pinned one, which is why a separate environment is
the correct shape here, not a workaround:

```bash
python -m venv /path/to/bridge-venv
/path/to/bridge-venv/bin/pip install 'agent-client-protocol[http]' uvicorn pyyaml
/path/to/bridge-venv/bin/python -m pawbench.cpd.acp_remote_eval.bridge \
    --command "/path/to/QwenPaw/venv_312/bin/qwenpaw acp" --port 8472
```

`pyyaml` is there because importing this package pulls in the grader's task
loader, not because the transport needs YAML.

### If one environment is a hard requirement

A single venv can hold both, because `import acp` resolves per process.  Install
1.0 into it, keep the old copy beside the venv, and give the agent a wrapper that
prepends it -- the bridge then imports 1.0 and the agent it spawns imports the
old one, still meeting only on the wire:

```bash
VENV=/path/to/QwenPaw/venv_312
cp -R "$VENV/lib/python3.12/site-packages/acp" "$VENV/legacy-acp/acp"
"$VENV/bin/pip" install --upgrade 'agent-client-protocol[http]'

cat > "$VENV/bin/qwenpaw-acp-legacy" <<'SH'
#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
export PYTHONPATH="$here/../legacy-acp${PYTHONPATH:+:$PYTHONPATH}"
exec "$here/qwenpaw" acp "$@"
SH
chmod +x "$VENV/bin/qwenpaw-acp-legacy"
```

Then pass `--command "$VENV/bin/qwenpaw-acp-legacy"`.  Verified with QwenPaw
2.2.2: bridge on 1.0.0, agent on 0.10.1, `initialize` answers
`protocol_version: 1`.

Two costs, both real.  Every other path that launches `qwenpaw acp` directly --
the desktop shell, an editor plugin, a script -- now imports 1.0 and dies on
`cannot import name 'text_block'`, so those need the wrapper too.  And a later
`pip install -e .` of the subject puts its pinned SDK back, which silently takes
`acp.http` away from the bridge; re-run the pip line above when that happens.

One backend process, sessions multiplexed across HTTP connections, updates
routed by session id, and the agent's own stderr left inherited (a piped stderr
nobody reads deadlocks a chatty agent, and the reason a prompt failed is usually
in those lines).  `--debug` logs every forwarded call.

Two things this does *not* do: it does not configure the agent (a `qwenpaw acp`
whose configured provider is missing answers `initialize` and then fails the
first prompt), and it does not make a loopback agent reachable from another
machine -- bind `public_base_url` to an address the agent can actually open.

`status`, `watch`, `detail`, `report` and `cancel` read the same job back; every
one of them is one documented request, so what this tool can do, `curl` can do.
The token rides a single `Authorization` header -- never printed, never placed
in a URL. Exit codes: `0` the job finished, `1` the command itself failed, `2`
the job ended `failed` or `canceled`, `3` a watch ran out its own clock while the
job was still moving.

Local submission is this CLI rather than `run_bench.py --agent acp`:
`RemoteAcpAgent` is deliberately absent from `pawbench/agents/factory.py`,
because that file hard-codes its registry and adding a branch there is the merge
conflict this package exists to avoid (design §2.1).

## What does not exist yet

The dashboard (M3) and the MCP tools plus the dataset-authoring skill (M4) now
ship in `plugins/pawbench-eval`, which proxies this service rather than speaking
to it from the browser. Still missing: the grading sandbox for uploaded custom
grading code (M5), so `custom` datasets are accepted, stored and resolved, but
their grading code runs in-process -- do not upload grading code from an author
you would not let run on this host. Task labelling -- which built-in tasks are
safe to offer remotely -- is still a manual list.

Operators and submitters: `pal_sdd/feat_acp_remote_eval/manual_acp_remote_eval.md`
(Chinese) is the user-facing manual; this file stays the developer's entry point.

## Design and acceptance

`pal_sdd/feat_acp_remote_eval/` holds the four documents: `prd_` (why and for
whom), `design_` (interfaces, state, failure taxonomy, security),
`test_` (case matrix and the M1 execution record), `acceptance_` (settled
decisions D1-D23, per-criterion conclusions, open items with owners).
