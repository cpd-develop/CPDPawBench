# PawBench × acp-remote-eval：架构与流程视图

> **回答什么**：`acp-remote-eval` 和原有 PawBench 是什么关系，以及同一道题在两条链路上分别怎么走。
> **视图状态**：current state（分支 `feat/acp-remote-eval`，2026-11-11）。代码已在盘上、尚未 commit；`git diff` 证实核心源码与共享依赖零改动。
> **产出方式**：场景技能 `system-modeler`（边界）+ `flow-visualizer`（流程），格式基础 `graphviz`。

## 一句话结论

**是旁挂扩展，不是改造，也不是分叉。** 整个特性对原有核心的依赖只有 **3 处 import**；它复用核心的 agent 生命周期契约、题库格式与判分语义，把「一次性 CLI + 我们提供的容器」换成「常驻服务 + 对方自带环境（BYO）+ 自建 HTTP 数据面」。`run_bench.py` 不 import 这个包，这个包也不 import CLI —— 只跑本地 benchmark 的安装完全不受影响（`README.md:6-8`）。

## 三份图，按这个顺序读

| 顺序 | 文件 | 回答的问题 |
|---|---|---|
| 1 | `pawbench_acp_boundary.dot` / `.svg` | 两者是什么关系？边界在哪、复用了什么、绕过了什么 |
| 2 | `eval_flow_local_vs_remote.dot` / `.svg` | 同一道题，本地链路与远端链路各走什么步骤、差在哪 |
| 3 | `remote_attempt_sequence.dot` / `.svg` | 远端单题下钻：文件怎么过去、产物怎么回来、分怎么打 |

`dashboard.html` 是三张图的可看版本（纯 CSS 标签页 + 1:1/适应宽度切换，无 JS、无外部依赖）。
**`.dot` 是唯一真源**，`.svg` 与 `dashboard.html` 都是派生物，不要手改。

## 复用边界：全部只有 3 条

| # | 扩展侧 | 核心侧插槽 | 复用什么 |
|---|---|---|---|
| ① | `harness.py:28` | `pawbench/agents/base.py:11` `BaseAgent` | 继承生命周期 `setup/run/teardown/post_run_collect/extract_transcript`，让 grader 看到普通 `execution_result`，不需要新模式 |
| ② | `service/datasets.py:36` | `pawbench/task_loader.py:25,81` `Task` / `TaskLoader` | 题库格式与加载：`load_task` `:548,557`、`load_all_tasks` `:1231` |
| ③ | `service/grading.py:31-40` | `pawbench/grader.py` 8 个 helper | 判分**语义**：`_grade_automated`、`_combine_grades`、`_build_judge_prompt`、`_format_grading_criteria`、`_normalize_judge_response`、`_parse_judge_text_response`、`_summarize_transcript`、`GradeResult` |

穷尽性核对：`pawbench/cpd/` 下**没有**任何 `pawbench.runner` / `pawbench.backend` / `pawbench.envs` / `pawbench.llm` / `pawbench.agents.factory` / `run_bench` 的 import；核心侧也**没有**任何指向 `cpd/` 的引用。依赖是单向的。

按 `.qoder/rules/cpd-extension-over-core-edit.md` 的四路判定：①②③ 走**第 1 路**（插槽已存在，扩写）；`AgentFactory` 走**第 3 路**（插槽不存在，先提需求）——`_REGISTRY` 硬编码在 `factory.py:32,52`，仓库内无动态注册点，所以 `RemoteAcpAgent` 故意不注册，`run_bench.py --agent acp` 这条路首期不存在（`design_acp_remote_eval.md:77`、`harness.py:11-14`）。

## 绕过 / 替换：不调用，但语义对齐

| 核心件 | 扩展侧替代 | 为什么 |
|---|---|---|
| `run_bench.py:389` + `runner.py:54` + `backend.py:185` | `service/queue.py:228` + `runtime.py:189` + `jobs.py` | 一次性进程内编排 → 常驻队列、全局并发 4、租约、UTC 运行窗口、调序/取消 |
| `envs/` Docker\|Local（`backend.py:261-285`） | 不建任何环境对象；`setup(environment=None)` `harness.py:127` | 被测方自带环境，结果硬编码 `environment="byo"` `harness.py:263` |
| `agents/factory.py` + `agents/impl/*` | `service/runner.py:325` 直接 `new RemoteAcpAgent` | 避免改核心注册表带来的合并冲突 |
| `grader.grade_task:67` + 同步 urllib judge `:288/:337` | `Scorer:234` + `LlmJudge.ask:169`（异步、退避上限 30s `:63`） | 入口绕过、helper 复用；`grade_task` 在 cpd 内**从未被调用**（已 grep 确认） |
| `llm/model_config.py` | `service/config.py:105` `JudgeConfig` | judge 配置独立，不走核心 provider 解析 |

## 新增模块清单（图里为可读性做了归并，明细在此）

| 模块 | 职责 | 关键符号 |
|---|---|---|
| `cli.py` | 提交侧 HTTP 客户端，一条命令一个请求 | `EvalClient:69` / `_cmd_submit:144` |
| `harness.py` | 每题一次 attempt 的 ACP harness + manifest-in-prompt 协议 | `RemoteAcpAgent:76` / `PROTOCOL_VERSION_TAG:54` |
| `acp/client.py` | ACP 传输与会话；自动批权限、拒绝 `fs/*` `terminal/*` 委托 | `connect:566` / `new_session:396` / `:246` |
| `acp/transcript.py` | ACP `session/update` → grader 事件形状 + 逐字 JSONL | `TranscriptRecorder:97` / `find_model_reported:77` |
| `redact.py` | 日志里去掉 URL 的 query/userinfo | `url_without_credentials:12` |
| `service/daemon.py` | 装配根：HTTP 与调度 tick 共用一个 loop | `build_service:114` / `serve:189` |
| `service/api.py` | FastAPI，控制面 + 数据面 | `create_app:306` / `_add_control_routes:445` |
| `service/auth.py` | 白名单 token 校验与签发 | `TokenVerifier:69` / `add_subject:219` |
| `service/config.py` | YAML → dataclass，相对路径锚定配置目录 | `EvalConfig:127` / `load_config:198` |
| `service/queue.py` | 全局排序与并发闸 | `JobQueue:101` / `tick:228` |
| `service/runtime.py` | 租约、启动对账、取消、job 收尾 | `EvalRuntime:102` / `tick_once:189` / `reconcile:137` |
| `service/schedule.py` | UTC 窗口 + 可注入时钟 | `resolve_window:104` / `FrozenClock:45` |
| `service/jobs.py` | 提交快照、归属、上限、调序 | `JobService:83` / `submit:103` |
| `service/datasets.py` | 内置目录 + 自定义集 CRUD/zip/resolve | `DatasetService:274` / `resolve:729` |
| `service/exchange.py` | 自建数据面：manifest、预签名、run token、收产物、重建 workspace | `Exchange:293` / `build_manifest:314` / `accept_artifact:458` / `rebuild_workspace:575` |
| `service/grading.py` | 异步判分包装 | `Scorer:234` / `LlmJudge:153` / `JUDGE_UNAVAILABLE:49` |
| `service/reports.py` | `shared`/`full` 两档、结果、报告、轨迹分页 | `Reports:98` / `job_detail:118` |
| `service/store.py` | stdlib SQLite（WAL），同步 API | `Store:213` |
| `service/attempts.py` | 活跃 attempt 的内存登记表 | `AttemptRegistry:39` |
| `service/pilot.py` | 固定 pilot 集 + 启动时组成校验 | `seed_pilot:162` / `composition_gaps:90` |

HTTP 面：数据面 `GET /healthz`、`GET …/assets/{dest}`、`PUT …/artifacts/{path}`、`GET /v1/reports/{job}/{file}`（`api.py:361,369,405,384`）；控制面 jobs / datasets / dataset-categories / detail / results / report / transcript / artifacts（`api.py:535-861`）。鉴权只有一道闸：控制面 Bearer 白名单（`authenticate:456`），数据面 GET 用 HMAC `expires+sig`、PUT 用带预算的 run token。绝对 URL 只由 `public_base_url` 拼出，**禁止回退请求 `Host`**（`api.py:14-17`）。

> 图 1 为可读性把 `api.py` 与 `exchange.py` 归并成「入口」和「数据面」两个框；实际路由在 `api.py`，逻辑在 `exchange.py`。图 3 的 `api.py:369/:405` 标出了真实落点。

## 证据与置信度

- **high**：以上所有 `path:line` 均来自本次直接读码与 grep；`git status --short` / `git diff --stat` 证实改动只有 `.gitignore`（+13）与一份无关特性的报告，`requirements.txt` / `pyproject.toml` **无 diff**，新依赖隔离在 `pawbench/cpd/acp_remote_eval/requirements.txt`。
- **high**：`by_environment` 分档维度存在于 `service/reports.py:209`；`environment="byo"` 存在于 `harness.py:263`。
- **medium（设计取舍，非代码强制）**：「byo 不与同环境 harness 混排」是榜单口径决策，见 `design_acp_remote_eval.md:280`；代码目前只提供分档维度，没有强制阻止混排的闸。
- **unknown（图 3 第 8 步）**：被测方机器内部执行不可观测，我们只看得到 ACP `session/update` 与最终上传。图中以虚线框标出，没有画成完整 happy path。

## 已知缺口与待验证

1. **判分沙箱未建**：`_grade_automated` 在工作线程里执行（`grading.py:266`），核心 `grader.py:141` 是 `exec(grading_code)` **进程内**执行，且 `:149-181` 会把 `subprocess` 换成日志包装器而非禁用。cpd 内无任何 docker/容器隔离。接受提交者脚本等于交出评分机 —— 这是**已知缺口，不是现状保障**。现有缓解只有 prompt 注入围栏（`grading.py:77-85`）与上传文件名/后缀 allowlist（`exchange.py:520-562`）。
2. **里程碑编号在两份文档里不一致**：`README.md:93` 把判分沙箱记为 **M5**，`design_acp_remote_eval.md:476` 把它记在 **M4**（`:477` 的 M5 是任务打标 + 榜单分档）。图里因此**不标沙箱的里程碑号**，只标「未建」。需要有人对齐这两处。
3. **看板（M3）、MCP + 出题 skill（M4）未建**：cpd 与 tests/cpd 下没有任何 `.html/.js/.ts/.tsx`，也没有 `*mcp*` 文件。图中一律红虚线目标态。
4. **任务打标仍是人工清单**（`README.md:95-96`）：哪些内置题适合远端开放，没有机器判定。
5. 测试现状：`tests/cpd/acp_remote_eval/` 24 个文件、479 个 `def test_`，含真 uvicorn + 真 ACP stdio 子进程的 e2e（`test_runner_e2e.py`、`tools/fake_acp_agent.py`）。本次只读代码，**未重跑测试**。

## 重新生成

```bash
npm i --prefix /tmp/pawbench-dot @viz-js/viz
node pal_sdd/feat_acp_remote_eval/architecture/render.mjs
```

依赖装在仓库外的临时目录，不给这个 Python 仓库引入 node 依赖；换位置设 `VIZ_PKG_BASE`。
脚本会重渲染目录下所有 `.dot` → `.svg`，并重建 `dashboard.html`。

## 维护提示

- 改了 `pawbench/cpd/` 的模块划分或复用关系 → 改图 1；改了执行步骤 → 改图 3；两条链路差异变了 → 改图 2。
- **改标签后必须复核文字溢出**：浏览器实测 CJK 字形比 graphviz 内置度量略宽，默认 margin 会让文字压出边框。各 `.dot` 的 `node margin` 已放宽到 `0.22~0.24,0.10`；本次已用浏览器 `getBBox()` 逐节点核对，三张图溢出数均为 0。
- 新增节点/边请带上 `path:line`；推断或目标态一律虚线并标注，不要画成现状。