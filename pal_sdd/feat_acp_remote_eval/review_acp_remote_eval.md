# acp-remote-eval 提交前独立检视记录

## 独立检视记录（第一轮：M1 全量代码）

- 检视者：5 个独立 subagent 上下文（general-purpose），分别负责 服务与并发 / 数据面与交换 / ACP 客户端与 harness / 鉴权与评测集 / 测试与端到端
- 检视时间：2026-11-10 14:20–14:50（Asia/Shanghai）
- 检视范围：`feat/acp-remote-eval` 分支上本特性全部未提交新文件——`pawbench/cpd/acp_remote_eval/**` 18 个、`tests/cpd/acp_remote_eval/**` 15 个、`pawbench/cpd/__init__.py`，共 33 个文件、约 4700 行
- 提供的材料：改动文件全文、`git status --porcelain -uall` 文件清单、四份规范（`rules/pre-commit-independent-review.md`、`rules/logging-quality.md`、`rules/code-craft-and-readability.md`、`rules/cpd-extension-over-core-edit.md`）。**未提供作者的方案说明与设计取舍**（design_ 文档未给出）
- 执行记录：检视前 `pytest tests/cpd/acp_remote_eval -q` → 242 passed；检视后见「复检」小节

发现项约 60 条，按严重度分层。**严重 7 条全部处理**，逐条如下（位置为修复前所在行）。

| # | 严重度 | 位置 | 发现 | 为什么是问题 | 处理 |
|---|---|---|---|---|---|
| S1 | 严重 | `service/api.py` PUT 路由、`service/runner.py:run_job/run_task`、`harness.py:post_run_collect/execution_result` | 事件循环线程上做同步 IO：整份上传体 SHA-256 + `os.replace` + SQLite 写、`store.get_job`、`plan()` 里逐题读任务 markdown、`rebuild_workspace` 复制全部 fixture | 数据面路由与 runner 共用服务事件循环；一次 50MB 上传或一次 15 题的 plan 会把所有并发任务的 GET/PUT 与心跳一起卡住。store.py 模块契约写明「事件循环内调用方必须走 `asyncio.to_thread`」，实际无处遵守 | 已修：上述 4 处改为 `await asyncio.to_thread(...)`（api.py 的 `accept_artifact`、runner 的 `get_job`/`plan`/`record_plan`/`update_job_task`/`_record`、harness 的 `rebuild_workspace`/`execution_result`） |
| S2 | 严重 | `service/auth.py:StaticConfigVerifier` | 文档字符串声称白名单文件改动会被运行中的校验器读到，但 `verify()` 从不重读文件 | 撤销一个 token 需要重启服务才生效——对外承诺与实际能力不一致，运维会以为已经吊销 | 已修：`from_file` 记录路径与 `(st_mtime_ns, st_size)` 指纹，`verify()` 先 `_refresh_if_changed()`；重读失败保留上一份可用记录并 `logger.warning(..., exc_info=True)`，避免半写入的文件把所有人踢出登录 |
| S3 | 严重 | `harness.py`（原 `timeout_seconds` 解析） | `int(x or y or 0) or None` 把 `0`、空串、非数字统一变成 `None`，`asyncio.wait_for(..., None)` 即无超时 | 一个坏数字让该次运行永久占住全局 4 个并发位之一，直到进程重启；night 窗口内会静默吞掉后续所有任务 | 已修：新增 `_resolve_timeout(requested, declared)`，任何不可用值回落到 `DEFAULT_TASK_TIMEOUT_SECONDS=1800`，超过 `MAX_TASK_TIMEOUT_SECONDS=4*3600` 被拉回；回落打 warning 带 requested/declared 上下文 |
| S4 | 严重 | `acp/client.py:AcpSession.close/spawn_command` | `contextlib.suppress(Exception)` 吞掉关闭失败；`spawn_agent_process` 返回的 `Process` 句柄被丢弃；`await task` 无超时 | agent 自己退出或卡住时子进程成为孤儿，stderr 管道不再被读；每题泄漏一个进程，一晚 15 题 ×N job 会把机器填满僵尸进程 | 已修：`AcpSession` 持有 `process`，`close()` 用 `wait_for(..., CANCEL_CLOSE_GRACE_SECONDS=5.0)` 做有界取消，`_kill_process()` 对仍在运行的子进程 `kill()` + `PROCESS_EXIT_GRACE_SECONDS=2.0` 回收，关闭失败不再静默而是 `logger.warning` 带 job/task 上下文 |
| S5 | 严重 | `service/queue.py:tick`、`service/store.py` | tick 是「读 running 集合 → 算空位 → 逐条 UPDATE」，锁只覆盖单条语句，整轮无事务；`update_job` 无条件写 | 与 cancel／另一轮 tick／API 线程并发时可超发 `max_concurrent_jobs`、把刚 canceled 的 job 复活成 running、scheduled→queued 重复推进；被复活的 job 会被 runner 真的跑起来，看板却显示 canceled | 已修：`Store.admit_job` 把两条限额做成语句内子查询计数并加 `status = 'queued'` 守卫，`Store.transition_job(..., from_status=...)` 用 `WHERE status = ?` 返回是否真的移动；`tick` 拆成 `_promote_scheduled`/`_start_queued`，本地计数器降级为快路径、SQL 为唯一裁决 |
| S6 | 严重 | 架构：服务重启后 running 任务无人回收（design C5） | 进程重启，`jobs.status='running'` 的行留在库里，`AttemptRegistry` 是内存对象因此 attempt 全部消失；远端 agent 之后 PUT 会得到 `attempt_not_running` | 服务不可能不重启（常驻正是本特性的目标）。重启一次，那一夜的任务全部变成不可解释的半程状态 | 未修（登记遗留 → M2 第 1 项）：本轮无守护进程入口（`README.md` 明确「no daemon entry point」），lease/heartbeat 没有可挂的循环。**M2 的验收门槛**：常驻入口与 reconcile 同批交付，二者缺一不许合入 |
| S7 | 严重 | `service/datasets.py:create_builtin_view/register_custom` | 直接 `upsert_dataset`，而 upsert 会保留库里的 owner；`register_custom` 在写库前先 `_copy_package`（内含 `rmtree`） | 任何人用一个已存在的 dataset id 就能把别人的题目、分类、描述整份换掉，而目录仍显示原作者——此后所有提交按换掉的题目判分；custom 路径还会在被拒绝之前先把对方的 fixture 文件删了 | 已修：新增 `_check_no_takeover(dataset_id, owner)`，命中他人 id 抛 `DatasetError("dataset_exists")`；create_builtin_view 在过滤前拒绝，register_custom 在校验通过后、`_copy_package` 之前拒绝 |

测试基础设施严重项（由「测试与端到端」上下文提出）：

| # | 严重度 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| T1 | 严重 | `tests/cpd/acp_remote_eval/test_runner_e2e.py:env` | 清理代码在 `yield` 之后：健康检查或 `Env(...)` 构造失败时，uvicorn 线程、监听端口与 SQLite 连接全部泄漏，且 `thread.join()` 结果从不校验 | 已修：`Store.close` 与 `_shutdown(server, thread)` 改为 `request.addfinalizer` 注册（finalizer 反序执行，先停服务再关库），并在 `_shutdown` 内断言线程真的退出 |

一般／建议项中本轮一并修的：

- 匿名 PUT 探测差异（`service/api.py`）：先用 `registry.lookup` 再校验 token，未授权者可用 404/403 区分「attempt 是否存在」。已改为 token 校验先于任何查询，缺 token 直接 `run_token_invalid`。
- 拒绝码日志分级（`service/api.py`）：安全拒绝与服务器故障混在同一级别。已拆 `_SECURITY_CODES`（info）、`_SERVER_FAULT_CODES`（error）、其余（warning）。
- stderr 与 argv 脱敏（`acp/client.py`）：`describe()` 会把带凭据的 URL 与命令行原样打进日志。已加 `_without_credentials`（去 query、去 userinfo）与 `_SECRET_WORDS` 参数脱敏。
- `spawn_command` 文档字符串与实际不符（声称已区分「崩溃」与「仍在思考」，实际未做）。已改为如实说明该判断尚未实现。
- runner 的 `teardown()` 异常会跳过 `registry.drop` 与 `_record`，导致 attempt 泄漏且这题无痕。已放进独立 `try/except` + `logger.exception`，`finally` 仍执行注销与记录。
- `admit_job`／`transition_job` 初版引用了 store.py 中不存在的 `STATUS_*` 常量（queue.py 才有）。已改用与 `count_running` 一致的字面量。

## 复检记录（第二轮：修复后的代码）

- 检视者：3 个新的独立 subagent 上下文（general-purpose），分别负责 队列／存储／runner 并发、数据面 IO 与资源、鉴权与评测集归属
- 检视时间：2026-11-10 15:00–15:06（Asia/Shanghai）
- 提供的材料：第一轮修复后的文件全文 + 文件清单 + 同一批规范；仍未提供作者方案说明。队列上下文额外被问「准入是否原子、测试是否钉住行为」
- 执行记录：复检前 261 passed；本轮修复 + 补测后 **267 passed, 1 warning in 9.45s**；再补三条"只有生产分支、没有断言"的新码用例后 **270 passed, 1 warning in 10.08s**（`pytest tests/cpd/acp_remote_eval -q`）

第二轮严重项 13 条（R1–R13），处理如下（位置为检视时所在文件）。

| # | 严重度 | 位置 | 发现 | 为什么是问题 | 处理 |
|---|---|---|---|---|---|
| R1 | 严重 | `service/queue.py:cancel` | 读状态后用无守卫的 `update_job` 写 canceled | tick 在这两步之间准入时，行被写成 canceled 而 runner 已经在跑，且 `was_running=False`，调用方不会去停它——看板显示已取消、远端 agent 仍在干活 | 已修：改用 `transition_job(from_status=读到的状态)`；守卫失败即重读再试（上限 `_CANCEL_ATTEMPTS=4`），已终态则 `job_already_finished` |
| R2 | 严重 | `service/queue.py:admit` | 同样是 `update_job` 无条件写 status | insert→admit 之间落地的 cancel 会被覆盖回 queued，等于从 canceled 准入 | 已修：新增 `STATUS_NEW`（行已写入但尚未入队），`admit(..., from_status=STATUS_NEW)` 走守卫，失败抛 `job_not_admissible`；`tests/…/test_queue.py::test_a_cancel_between_insert_and_admit_is_not_overwritten` 钉住 |
| R3 | 严重 | `service/runner.py:run_task` | `except Exception` 接不住 `CancelledError`：`finally` 之后 `_record` 被跳过，task 行永远停在 running，同一 job 剩余 plan 停在 pending | 全局 4 个槽位按行计数，一个永不落定的 running 行永久占位；设计文档在 3 处引用 `failed(recovered)` 却无实现 | 已修：新增 `except BaseException` 分支，用 `asyncio.shield(to_thread(_record))` 记 `failed(interrupted)` 后重抛；三条早停分支合并为 `_blank_result()`（原为三处近乎复制的字面量）。「重启 reconcile／lease」仍是 S6 遗留，M2 第 1 项 |
| R4 | 严重 | `service/store.py:admit_job` | 每人限额按调用方传入的 submitter 计数 | 传错就静默失效——限额变成没有 | 已修：去掉该参数，SQL 子查询按行自身 `jobs.submitter` 相关计数；queue 与 6 处测试调用同步更新 |
| R5 | 严重 | `service/api.py` PUT 路由 | 先读完整请求体、后进线程才校验 token | 猜到三元组的人用垃圾 token 就能让服务按 N×64 MiB 占内存——限额拦的是体积，不是「谁在发」 | 已修：`Exchange.check_run_token()` → `RunTokenVault.check()` 在 `_read_body` 之前拒绝，只验证不消费 |
| R6 | 严重 | `service/exchange.py:accept_artifact` | `authorize` 在路径/体积校验之前消费额度 | 64 次被拒的 PUT 能把额度花光，真正的答案随后得到 `run_token_spent` | 已修：额度改为文件落盘后消费；`test_a_refused_upload_does_not_cost_the_run_a_slot`、`test_checking_a_token_leaves_the_whole_budget_intact` |
| R7 | 严重 | `service/exchange.py:RunTokenVault.authorize` | 无锁的「查额度→自增」，而 `accept_artifact` 已按第一轮 S1 移入 `asyncio.to_thread` | 第一轮的修复本身引入的竞态：两个线程可花掉同一个额度，`revoke`/`status` 也可能在字典变大时迭代 | 已修：`threading.Lock` 覆盖 `issue/check/authorize/status/revoke`，并在 `issue` 内顺带清理过期 grant（原 `_grants` 无上限）。`test_a_single_upload_slot_is_not_spent_twice_by_two_threads` 钉不变式——注：该用例在无锁版本下通常也通过（GIL 使竞态窗口很小），属于回归防护而非鉴别性测试 |
| R8 | 严重 | `service/exchange.py:rebuild_workspace` | 记录在库、磁盘缺失的 artifact 只 `logger.warning` 后继续 | 判分进程会把「答案文件是空的」当成 agent 的作答打分，`classify` 仍返回 finished | 已修：抛 `ExchangeError("artifact_missing")`，该行变成带原因的 failed |
| R9 | 严重 | `acp/client.py:close` | `except Exception` 接不住 `CancelledError`：取消时 teardown 与 `_kill_process` 全被跳过，且 `runner` 的 `except Exception` 同样看不见它 | 子进程成为孤儿、stderr 管道不再被读、registry 条目永久留存——正是第一轮 S4 想根治的泄漏，只是换了触发路径 | 已修：kill 移入 `finally`，取消与超时分支显式捕获 `CancelledError`；`_kill_process` 改为同步并容忍 `ProcessLookupError`（回收交给子进程 watcher，`PROCESS_EXIT_GRACE_SECONDS` 随 `wait()` 一起删除） |
| R10 | 严重 | `harness.py:setup` | `build_manifest` 直接在事件循环上逐 fixture 读盘 + SHA-256 | 与 store.py 模块契约矛盾；一个多附件任务会卡住整个数据面 | 已修：`await asyncio.to_thread(self.exchange.build_manifest, ...)` |
| R11 | 严重 | `acp/client.py:initialize/new_session`、`harness.py:post_run_collect` | 握手两步与 collect 都无期限 | 起进程但不说话的 agent 会无限占住队列槽位、run token 与 registry 条目 | 已修：`_bounded()` 给两步握手加 `HANDSHAKE_TIMEOUT_SECONDS=30`，超时抛 `AcpError("acp_handshake_timeout")`；collect 加 `COLLECT_TIMEOUT_SECONDS=300`，runner 新增 `failed(collect_timeout)` 分类（不与 `runner_error` 混为一谈） |
| R12 | 严重 | `service/datasets.py:assign_categories` | 不接收 `Principal`、不查 owner | 任何白名单用户都能改写别人 dataset 的分类，且新分类 `created_by` 记在受害者名下——分类是选择器入口，等于给别人决定哪些提交会命中该评测集 | 已修：与 `delete_dataset` 同一 owner-or-admin 规则，参数改为 `principal`，新分类归属实际操作人；新增 stranger 拒绝断言 |
| R13 | 严重 | `service/datasets.py` 包校验 | 无文件数/字节数上限；`FORBIDDEN_PACKAGE_NAMES` 是 `SCORE_HIJACK_FILENAMES` 的手工副本且漏了 `usercustomize.py`，两者都不覆盖 pytest 默认收集的 `test_*.py`/`*_test.py` | 前者是一次上传把共享机磁盘写满；后者是判分机上真的会被执行的代码——同一个政策分成两份、两份都不全 | 已修：`FORBIDDEN_PACKAGE_NAMES = SCORE_HIJACK_FILENAMES`（一处政策）+ `_FORBIDDEN_NAME_PATTERNS` fnmatch；`register_custom` 落盘前先过 `MAX_PACKAGE_FILES=2000` / `MAX_PACKAGE_BYTES=256MiB` |

一般项本轮修的：`Store` 增加 `PRAGMA busy_timeout=_BUSY_TIMEOUT_MS=5000`（第二个连接抢写锁时不再让整轮 tick 抛 `OperationalError`）；`_checked_id` 拒绝 `.`/`..`（`_ID_RE` 的字符类放行它们，而 `attempt_dir` 直接拼接、`drop_attempt`/`rebuild_workspace` 会 rmtree 解析结果）；`client.py` close 的两条日志补 `reason=repr(exc)`；runner 的失败日志带上 `reason`；`harness.run` 的超时/失败原因不再只有 code。

登记遗留（一般／建议，责任人：anderson）：

| # | 位置 | 发现 | 计划 |
|---|---|---|---|
| L1 | `service/queue.py:_start_queued` | 窗口已关的 queued job 每轮 tick 都进 `window_closed` 并重打一条 info，列表无界；`test_queue.py` 把「仍是 queued」固化成预期 | M2 接守护循环时一并定：报告即落态（`skipped(window_closed)`）或去重；测试随之改写 |
| L2 | `service/queue.py:normalize_positions`、`store.queue_positions` | 每行一条独立事务（N 次 fsync），且把 finished/canceled 历史行一起重编号，`tail_position` 随历史增长 | M2：单事务 `executemany` + 只处理 ACTIVE |
| L3 | `service/api.py` GET 路由 | `Path.resolve()/is_file()` 与 `request.stream()` 在循环上、无请求期限 | M2：数据面读操作进线程，慢_body 加 deadline |
| L4 | `service/exchange.py` | 上传体先 `b"".join` 再整份 hash（最多 64 MiB 额外拷贝）；attempt 级无聚合字节预算；`.quarantine` 里 `*.part` 无启动清扫；`drop_attempt` 无生产调用方，staging/uploads/workspace 无保留策略 | M2：流式 hash + 每 attempt/job 字节上限 + 保留策略（与磁盘配额一起做） |
| L5 | `service/exchange.py:RunTokenVault.status/revoke` | 每次 teardown 扫全部在线 grant | L4 一并做按 (job, task) 索引；当前规模无感 |
| L6 | `service/datasets.py` | 校验与复制是对同一目录的两趟（uploader 仍可控盘）；`delete_dataset` 只删行，目录留在盘上且 id 可被下一个人 `rmtree`；`dest` 到运行时才拒；`describe` 每次重解析全部任务文件；分类列表 N+1 | M2 上传通道定型时一起做（先复制后校验、删除即清盘、`dest` 入包即校验、摘要缓存） |
| L7 | `service/auth.py` | 指纹是 `(mtime_ns, size)`，`cp -p` 或等长改动不会触发重读（docstring 的「撤销无需重启」仅对朴素编辑器成立）；白名单文件被删时读成空表→全员掉线；非 `str` bearer 变 500；重复 token 静默 last-wins；已撤销/权限不足的拒绝不打日志 | M2：按内容 hash 触发、空读保护、类型入口收敛、拒绝计数日志 |
| L8 | `harness.py`/`acp/transcript.py` | `stderr_tail(5)` 把第三方输出贴进日志（规则 3）；transcript 每条 update 一次同步写 | M2：日志只留长度/前 4 字节指纹；写批量化 |
| L9 | 架构 | job 级墙钟缺失：`run_job` 把 task 超时相加，一个 15 题 job 可远超任何单一期限 | 与 S6 同批（M2 第 1 项：常驻入口 + lease + job deadline） |
| L10 | 格式 | 38 行超过本仓库 `line-length = 100` | 单独一次纯格式化提交，不与逻辑改动混在一起 |

鉴别性检视结论（队列上下文专问「测试是否钉住行为」）：第一轮的 4 个 store/queue 新测试是单线程、且把竞争方排在调用之前，旧的 read-then-write 实现同样能过——已记录为真问题。本轮补的 R2 用例（insert 后 cancel 再 admit）、R6/R7 额度用例、R12/R13 归属与包政策用例是行为级的；`test_a_cancel_that_lands_mid_tick_is_not_revived` 的 monkeypatch 仍按函数名注入（改 patch `update_job` 需要先让 admit 回到无守卫写法，不做）。

修完之后自查发现的一类新问题：**新加的失败码有生产分支、没有断言**。`interrupted`（R3）、`collect_timeout` 与 `acp_handshake_timeout`（R11）当时只改了代码，测试里搜不到这三个字符串——等于「编译期写进了 taxonomy，运行期没人保证它还在」。已补三条用例（270 passed）：`test_runner.py::test_a_cancelled_attempt_is_recorded_instead_of_staying_running`（取消路径必须自己写行，否则该行永久占一个全局槽位）、`test_runner.py::test_an_attempt_we_could_not_assemble_is_not_a_runner_error`（collect 超时与 harness bug 是两个不同的机器）、`test_acp_client.py::test_an_agent_that_never_takes_the_handshake_does_not_hold_the_slot`（不说话 0.05s 内判超时）。三条都是把分支删掉就会红的鉴别性用例。

本轮未做的格式化项（L10，38 行超宽）留在 M1 提交前单独一次纯格式化提交，不与逻辑改动混在同一个 commit——规则见 `rules/code-craft-and-readability.md` 第 6 条。

## 复检记录（第三轮：M2 常驻进程切片）

- 检视者：1 个新的独立 subagent 上下文（general-purpose，task `a2401a9111d2da440`），耗时 290 s
- 检视时间：2026-11-10 16:22–16:27（Asia/Shanghai）
- 检视范围：`service/runtime.py`、`service/daemon.py`、`service/store.py`、`service/runner.py`、`service/config.py`、`__main__.py`、`config.example.toml`，以及 `test_runtime.py`、`test_daemon.py`
- 提供的材料：以上文件全文 + 文件清单 + 同一批规范（`code-craft`、`logging-quality`、`cpd-extension`）；未提供作者方案说明
- 报告结论：**有 2 项严重、5 项一般，严重项未修不建议 commit**。逐条清点实为 2 严重 / 7 一般 / 4 建议——报告小计与它自己的分类标题不一致，下表按逐条为准
- 执行记录：本轮开始前 335 passed；修复 + 补测后 **348 passed, 1 warning in 12.09s**（`pytest tests/cpd/acp_remote_eval -q`）

| # | 严重度 | 类别 | 位置（检视时行号） | 发现 | 处理 |
|---|---|---|---|---|---|
| M1 | 严重 | 未处理异常 | `daemon.py:157`、`runtime.py:185`、`config.py:181` | 调度协程从不被 await；`sleep(tick_seconds)` 在 try 之外；config 不校验 `tick_seconds` 为正。配成 0 时调度协程抛 `ValueError` 静默死亡，HTTP 面照常应答但不再排班，异常只以 "never retrieved" 出现 | 已修，三处一起：`config.py:190` 拒绝 `tick_seconds <= 0`（0 不是「一直 tick」而是「从不让出」，会把与数据面共享的事件循环饿死）；`runtime.py:183` 把 sleep 移进守卫；`daemon.py:193` `_stop_scheduler()` 以 `await asyncio.wait({scheduler})` + `cancelled()/exception()` 分流——自己死掉打 error 并带 `reason`，被取消打 info。用例：`test_config.py:123`、`test_daemon.py:271` |
| M2 | 严重 | 阻塞与卡顿 | `runner.py:278-282`、`harness.py:127-147` | `max_job_seconds` 只约束任务之间与 prompt 超时，`agent.setup()`（connect/initialize/new_session）不受墙钟管：远端接了连接却不完成握手即无界运行，且租约持续续期，墙钟与租约两道保险同时失效，4 个全局槽位可冻死 | 已修：`runner.py:133` `_attempt_deadline()`，`runner.py:342-352` 把 setup / prompt / collect 三步收进同一个 `asyncio.timeout` 窗口，用 `stage` 变量记住超时发生在哪一步（`runner.py:362-372`）：`collect` 仍归 `failed(collect_timeout)`（我们的机器），`setup`/`run` 归 `failed(deadline)`（墙钟到点）。用例：`test_runner.py:402`（1.5 s 墙钟内落定、实测 elapsed < 3 s、mail_a=failed/deadline、mail_b=skipped/deadline、日志 `stage='setup'`）、`test_runner.py:441`（collect 超界仍记 `collect_timeout`）|
| M3 | 一般 | 性能 | `runtime.py:361-390`、`runner.py:401-444` | `_skip_pending`／`skip_tasks` 逐行 UPDATE，每次 `store.execute` 独立事务并提交，与自身 docstring 的「inside a single transaction」矛盾；500 任务的 job 会连续占写锁数百 ms，把数据面上传排在后面 | 已修：新增 `store.py:681` `skip_unrun_tasks()`——一条 `UPDATE … WHERE job_id=? AND status='pending'`（可选 `attempt` 限定），返回 rowcount 给每个调用方记日志；`runtime._skip_pending` 与 `runner.skip_tasks` 两个调用点改走它。`store.settle_orphan_job` **不改**：它本来就是批量语句，且把三条写放在同一事务里、覆盖面是 `('pending','queued')`，换成 `skip_unrun_tasks` 会缩小语义并拆散事务。用例：`test_store.py:247`（只标 pending，running/finished 不动，`duration_s == 0.0`）、`test_store.py:280`（按 attempt 限定）|
| M4 | 一般 | 未处理异常 | `runtime.py:263-267` | `finally` 里的 `release_lease` 与其后的 `_finalize` 都没有兜底：任一 SQLite 异常就跳过 job 行收尾，job 永久停在 `running`，而全局并发按行计数 | 已修：`runtime.py:286-292` 把 release 包进 try/except，`logger.exception("lease release failed")`——租约会自己过期并被下一个 acquirer 拿走，job 行不会自己动。用例 `test_runtime.py:447`，并做过反向验证（见下）|
| M5 | 一般 | 未处理异常 | `runtime.py:399-419` | id 来自上一 tick 快照，期间被 cancel 的行仍会被标注 `window_closed`（把用户行为写成服务原因），且 `transition_job` 返回值被丢弃却固定打成功日志 | 已修：`runtime.py:412` 终态早返回；`runtime.py:430` moved 为假时降为 warn「job was closed by something else first」并返回 False。用例：`test_runtime.py:390` |
| M6 | 一般 | 资源泄漏 | `daemon.py:164-166` | `scheduler.cancel()` 后未 await 即 `store.close()`，线程池里在途的 `to_thread` 会在已关闭连接上执行；`shutdown()` 若抛异常，cancel + close 两行整体跳过 → 连接泄漏 | 已修：`daemon.py:178-190` 三步各自 try，各打一条 `logger.exception("exit step failed", extra={"step": …})`；顺序仍是「停在跑的作业 → 停调度 → 关库」。用例：`test_daemon.py:247` |
| M7 | 一般 | 资源泄漏 | `runtime.py:264-266` | `beating.cancel()` 不 await，`beat_lease` 可能排在 release 之后，把别人刚拿到的租约又续成"我的" | 已修：`runtime.py:279-285` `cancel()` 后 `with contextlib.suppress(asyncio.CancelledError): await beating`，再 release。用例：`test_runtime.py:408`（事件序列必须为 beat-start → beat-stop → release）|
| M8 | 一般 | 阻塞与卡顿 | `runtime.py:138-172` 被 `daemon.py:143` 同步调用；`runtime.py:336` 在 async `_finalize` 里同步 `get_job` | 全表 orphan 查询 + 每 job 一事务都跑在事件循环上，违反 `store.py:7-8`、`runtime.py:105-108` 自述的「一律走 to_thread」契约 | 已修：`daemon.py:153` `await asyncio.to_thread(service.runtime.reconcile)`；`runtime.py:322` `await asyncio.to_thread(self._cut_short_reason, job_id)` |
| M9 | 一般 | 日志 | `runtime.py:221-224` | 日志说「被另一个进程持有」，`extra` 里的 `owner` 却是自己——这条正是为「两个服务指向同一库」准备的，却答不出另一个是谁 | 已修：新增 `store.py:380` `lease_owner()`，`runtime.py:228` 补 `held_by`。用例：`test_runtime.py:386`（`held_by='proc-b'` 且 `owner='proc-a'`）、`test_store.py:406` |
| M10 | 建议 | 日志 | `daemon.py:53-63`、`client.py:180` | 新 formatter 会渲染所有 `extra`，而 `AcpEndpoint.http` 的报错消息带原始提交 URL；提交方 token 可以骑在 URL 的 userinfo 里被第三方错误消息原样重复，最终入日志 | 已修：`daemon.py:48` `_URL_CREDENTIALS`，`ContextFormatter.format` 出口统一替换为 `scheme://***@`（`daemon.py:73`）。这是凭据进文件前最后一个还来得及拦的位置。用例：`test_daemon.py:330`（`SEKRIT` 不出现，`127.0.0.1:9100/rpc` 保留）|
| M11 | 建议 | 性能 | `runtime.py:304`、`queue.py:223` | 拉全行（含 JSON 列）只为算 status；每 tick 全量 SELECT 等待队列只为 `len()`，无 LIMIT | 遗留 L11 |
| M12 | 建议 | 未处理异常 | `runner.py:356-374` | 二次取消时 `shield` 把 `_record` 甩在后台无人 await，gather 已结束，写没写成不可知 | 遗留 L12 |
| M13 | 建议 | 日志 | `runtime.py:159-171`、`runtime.py:466`、`runner.py:349` | 同一事件 per-job error + 聚合 warning 双份，孤儿多时是无界循环告警风暴；两处用 `repr` 代替 `logger.exception`，非预期退出丢栈 | 遗留 L13 |

越界检查（报告原文）：改动全在 `pawbench/cpd/acp_remote_eval/**` 与 `tests/cpd/**`；仓库根仅 `.gitignore` +4 行（忽略 `service/runtime/`），未触核心；无 `print`／`pdb` 残留；token 仅 `auth.py:158` 以指纹形式入日志，符合约定。

### 复检与反向验证

严重项 M1/M2 各自按「config／循环体／退出路径」与「attempt 窗口／stage 分类」三条分支逐一对着代码复看过，并跑全量：**348 passed**，无回归。

M4 单独做了反向验证：临时移除 `finally` 里的 try/except 后跑 `test_runtime.py::test_a_lease_release_that_fails_still_closes_the_job_row` → `sqlite3.OperationalError: database is locked` 冒出、用例失败；恢复守卫后 `test_runtime.py` 24 passed。这条同时也是本轮唯一一次实测「测试是否鉴别修复」，其余各条按「把修复分支删掉即改不到断言的状态」逐条构造断言（M1 断 `reason` 属性、M2 断 `stage` 与两个不同 failure 码、M3 断 running/finished 行不动、M5 断行未被改写、M7 断事件顺序、M9 断 `held_by`、M10 断密文不出现在渲染结果里）。

### 本轮自查另发现的一处（不在报告内）

`service/store.py` 里 `lease_owner` 被定义了两次（380 与 681）——一次编辑方向写反造成的重复。两份函数体相同，后者静默覆盖前者，测试照常全绿，属于「读的人才会踩」的缺陷。已删除第二份，保留与 `acquire／beat／release_lease` 同组的那一份；删除后 348 passed 不变，可反证两份确实等价。同时用 AST 扫了整包的类内重名方法，除 `BuiltinCatalog.tasks`（property + setter，合法）外无同类问题。

### 登记遗留（本轮新增，责任人：anderson）

| # | 位置 | 发现 | 计划 |
|---|---|---|---|
| L11 | `runtime.py:304`、`queue.py:223` | 只为算 status 拉全行；只为 `len()` 全量 SELECT 等待队列，无 LIMIT | M2 接 submit／manifest API 时一并改成 `SELECT status, COUNT(*)` 与 `EXISTS … LIMIT 1` |
| L12 | `runner.py:356-374` | 二次取消时 `shield` 的 `_record` 无人 await，写入结果不可知 | 与重试路径同批（retry 落地后这条才真正可达）|
| L13 | `runtime.py:159-171`、`runtime.py:466`、`runner.py:349` | 孤儿 job 的 per-job error + 聚合 warning 双份；两处 `repr` 代替 `logger.exception` 丢栈 | M2 收日志规范时统一（规则见 `rules/logging-quality.md` 第 2、4 条）|
| L14 | 架构 | 周期租约清扫缺失：`running` 行的租约若已被异常路径释放，只在下一次重启 reconcile 时被结算 | 待判定：每 tick 扫一遍会改掉「重启才结算」的语义，先记不修 |
| L15 | `test_runtime.py::test_shutdown_cancels_every_run_and_leaves_nothing_running` | 优雅退出的作业被断言成 `service_restarted`，语义存疑（是「我们重启了」还是「我们停掉了它」）| 与 L14 同批定，随后改写断言 |
| L10 | 格式 | 超过 `line-length = 100` 的行由 38 增至 **49 行 / 16 文件**（M2 切片带来 11 行）| 单独一次纯格式化提交，不与逻辑改动混在同一个 commit |
| L16 | 测试缺口（M8 的覆盖） | M8 的两处 `to_thread` 改动**没有鉴别性用例**：单线程用例看不出一次同步 SQLite 调用有没有占住事件循环，把 `to_thread` 拆掉现有 348 项照样全绿。见 `test_acp_remote_eval.md` §4.8 的如实标注 | anderson — 补一个「store 查询睡 50 ms + 另起协程探活」的循环卡顿回归用例，与 L11 同批（提交 API 落地后数据面才真的与调度器同进程竞） |

前两轮登记的 L1–L8 状态不变；**L9（job 级墙钟）已关闭**——题间墙钟随切片第一批交付（`test_acp_remote_eval.md` §4.7 的 L9 行），本轮 M2 的 `_attempt_deadline` 补上 attempt 内部那一格（"远端接了连接却不完成握手"），两者合起来才是 L9 要的「一个 15 题 job 不再只受单一期限约束」。第一轮的严重项 **S6（重启 reconcile／lease）同样已随常驻切片交付**，并由本轮复检其退出路径与心跳先后。

## 复检记录（第四轮：M2 收尾——CLI 提交路径、数据集路由、提交原子性与报表外发）

- 检视者：3 个新的独立 subagent 上下文（general-purpose），分工为 CLI 提交路径 / 数据集路由与 zip 上传 / 提交原子性与报表外发
- 检视时间：2026-11-10 20:40–20:49（Asia/Shanghai，三份报告同批回收）
- 检视范围：M2 收尾切片 7 个文件——`cli.py`(495)、`service/api.py`(965)、`service/datasets.py`(1092)、`service/jobs.py`(639)、`service/reports.py`(928)、`service/store.py`(821)、`service/pilot.py`(180) 及其测试；特性此时共 25 + 23 个 py 文件（后端 10 670 行、测试 9 977 行）。**未提供作者方案说明**，只给文件全文 + 清单 + 同一批规范
- 报告结论：CLI 上下文 1 严重／5 一般／3 建议；数据集上下文 2 严重／10 一般／一批建议；提交与报表上下文 3 严重／7 一般／5 建议。合计 **6 严重**，全部处理，另加本轮自查 1 条（N7）
- 执行记录：本轮开始前 517 passed；6 条严重 + 3 条一般修完并补 6 条新用例后 **523 passed, 1 warning in 15.06s**（`pytest tests/cpd/acp_remote_eval -q`）

| # | 严重度 | 类别 | 位置（检视时行号 → 修复后） | 发现 | 处理 |
|---|---|---|---|---|---|
| N1 | 严重 | 日志／凭据外发 | `cli.py:461`＋`:119` → `cli.py:126`、`:368`、`:487` | 下载预签名报表链接时带着 `Authorization` 发往一条**只校验 sig、不校验 token** 的路由（`api.py` 报表路由），而 httpx 的异常文案会把整条请求 URL 拼进 `str(exc)`——`…?expires=…&sig=<HMAC>` 就此进 stderr／CI 日志。TTL 内拿到这行日志等于拿到可下载 full 档报表的链接 | 已修，两处一起：`to_file` 改用不带 `Authorization` 的独立 client（docstring 写明「签名本身就是那道门，bearer 在这里是死重，而且它会跟着异常文案出门」）；`_transport_failure()` 只打异常类型名与去掉 query 的 URL，`main` 兜住 `httpx.HTTPError` 走它。用例：`test_cli.py:329` 断言下载请求**没有** authorization 头、`test_cli.py:350` 让传输层抛一条把整条 URL 抄进消息的异常，断 sig 值、bearer、`sig=` 三种形态都不出现在 stderr，而 `/v1/reports/` 还在 |
| N2 | 严重 | 数据正确性 | `datasets.py:254/339`＋`store.py:589` → `datasets.py:684` | `upsert_dataset` 的 `ON CONFLICT DO UPDATE` 从不写 `kind`，而两个 create 入口都不查 kind：同一个 owner 拿已有的 custom id 走 `POST /v1/datasets`（或反向上传）就能换掉 `task_ids`/`filter_spec`，目录里那一行仍然自称 `custom`——`describe` 给出空 tasks、`tasks_for_run` 为空，判分指向不存在的任务，上传目录变孤儿。`dataset_kind_fixed` 当时只在 `edit_builtin_view` 有 | 已修：`_check_no_takeover(dataset_id, owner, kind)` 两道守卫（他人 id → `dataset_exists`；同 owner 跨 kind → `dataset_kind_fixed`，文案直接说「delete it and re-create it」），调用点 `:269`（builtin_view）与 `:362`（custom）各带自己的 kind。用例：`test_datasets_api.py:436` 同一 owner 先建 view 再传 package，两个方向各拒一次且两行的 `kind` 都没变 |
| N3 | 严重 | 资源泄漏／阻塞 | `api.py:589`＋`datasets.py:889` → `api.py:899`、`:592`、`datasets.py:383`、`:886` | 256 MB 的 zip 全量进内存三次（chunks → `b"".join` → `BytesIO`），而上传跑在默认线程池（~32 线程）上；几个并发上传足以把正在跑评测的常驻进程 OOM 掉——限额拦的是体积，不是「同时几份」 | 已修：`_stream_body_to_file()` 落 `mkstemp` 临时文件，先按 `Content-Length` 预拒、再按**逐块累计**真判（声明值属于调用方），`BaseException` 路径 `unlink`；`ZipFile(path)` 按路径打开，`io` 导入删除；路由把 archive 交给服务并在 `finally` 删临时文件。逐块写盘经 `asyncio.to_thread`，与同文件其余 IO 的契约一致。错误码 `package_too_large` → 413 |
| N4 | 严重 | 数据正确性／资源泄漏 | `jobs.py:213-253` → `store.py:468`、`:774`、`jobs.py:196` | job 行与 N 条快照是 N+1 次独立提交（`Store.execute` 一条语句一个事务），进程夹在两条中间就留下 `new` 行＋半份快照；`new` 既不在 tick 的读取范围（queued/scheduled）也不在启动 reconcile 的（running），该行永不清理——正是 `jobs.py` 顶部注释声称防住的失败 | 已修：`insert_job_with_datasets(job, datasets)` 在同一个 `with self._lock, self._conn` 里写完；列名表 `_JOB_INSERT_COLUMNS`（有序，供 INSERT）与既有 `_JOB_COLUMNS`（frozenset，供可更新校验）是两件事，**第一版误同名遮蔽后者导致 101 例红**（`set - tuple`），改名并加注释区分。用例：`test_store.py:474` 先断异常路径回滚（job 与快照都查不到）再断成功往返，`test_jobs.py:353` 断提交写入失败后库里没有需要人收拾的行 |
| N5 | 严重 | 未处理异常 | `jobs.py:151-161`、`:241-253` → `jobs.py:162`、`:259` | 两个缺口：`_write` 成功后 `queue.admit` 自己抛错（`tail_position`／`transition_job` 遇 `database is locked`）时行停在 `new`，无人补偿；补偿写自身若再抛，原始异常被替换、`logger.error` 不执行——提交方读到的是一条关于补偿的错，而不是真正失败的那条 | 已修：`admit` 放进 try，失败走 `_close_unfinished(job_id, submitter)`；后者守卫 `new`（中途落地的 cancel 保留自己的状态，与 `JobQueue.admit` 同一条规则）、绝不抛（两个调用点都在往外走另一个异常，兜底再抛会顶掉提交方要看的那条）、并按结果分级别。用例：`test_jobs.py:375`（cancel 夹在中间 → 行仍是 canceled，不会被写回 queued）、`test_jobs.py:399`（补偿再失败时 `str(raised.value)` 仍是原始那句 "snapshot write refused"，库里无残留行）|
| N6 | 严重 | 安全（凭据外发） | `reports.py:127/196/859` → `redact.py:12`、`reports.py:129/198` | `acp_url` 原文进 shared 档 detail、results 的 `environment` 与 markdown 首行，而 `http://user:token@host`、`?key=…` 都是**合法**的 ACP 地址（`AcpEndpoint.http` 只看 scheme）。同一代码库已经为日志写过两份脱敏（`daemon.py:_URL_CREDENTIALS`、`client.py:_without_credentials`，后者注释明说这串会落进 job 行），唯独可以转发给被测方的报表没用 | 已修：抽出 `redact.py::url_without_credentials`（去 query、去 `user:pass@`）。抽的理由写在模块 docstring 里，是「三处消费者 + 三条互斥的 import 图」：CLI 不能拖 ACP SDK，服务不能拖 CLI，不抽就是第三份副本。`describe()` 与报表渲染都改用它；markdown 继承已脱敏的 payload |
| N7 | 严重 | 安全（凭据外发） | `jobs.py:467`（自查，非报告项） | 上一轮把「`_job_item` 原样回吐 `acp_url`」判成「提交方看自己那一行，可接受」。判错了：同一个 `_job_item` 既喂 `GET /v1/jobs/{id}`，也喂 `GET /v1/jobs`——后者按需求 5 明确返回**所有人**的 job，等于把别人的端点凭据发给每一个持 token 的人 | 已修：与 N6 同一个函数脱敏；库里仍存原文，runner 要拿它重连（`runtime.py:81`）。用例：`test_jobs.py::test_the_queue_views_drop_the_endpoints_credential` 断三个事实——库行里密文出现两次（没被动过）、两个读视图都是 `http://eval.example.com/rpc`、整个 payload 的 JSON 文本里查不到密文 |

一般项本轮一并修的 3 条：

- **服务给的文件名不是路径**（`cli.py:182`）：`Path(str(link["filename"])).name`，空值回落 `report-<job>.<fmt>`；`--out` 仍是调用方自己敲的路径，只收窄工具自己发明的名字。用例 `test_cli.py:392`：把响应里的 filename 改成 `../../escaped.md`，文件仍落在调用者所在目录，上级目录没有多出文件。
- **提交补偿的日志级别与主体**（`jobs.py:246-276`）：`submission write failed` 原来只带 job_id，补 `submitter` 与快照条数；`_close_unfinished` 原来无论行有没有关掉都打 `error`——关掉是「系统自己恢复了」，按 `rules/logging-quality.md` 第 1 条降为 `warning`，只有行没被关掉（需要人介入）才保留 `error`，兜不住的那条走 `logger.exception`。
- **上传闸读的是活值**（`api.py:592` 前注释）：路由原来 `from .datasets import MAX_PACKAGE_BYTES` 按值绑定，检视者指出 `test_datasets_api.py:402` 的 monkeypatch 打的是 unpacker 那一侧，用例名（"before it lands"）与实际校验的不是同一处。改为运行期经模块属性读，并把异常从 `ExchangeError` 换成 `DatasetError`，让同一个 code 走控制面 handler（`_PACKAGE_GUARD_CODES` 的 `warning`）而不是被数据面 handler 记成 `info`。用例补两条断言：`"is over" in message`（只有路由的预检会说这句话）与 `GET /v1/datasets/big` → 404（什么都没落库）。

### 五类必查逐项结论

| 类别 | 结论 |
|---|---|
| 性能 | N3 之外无新增缺陷。报表与目录的重复解析（每任务一次 `list_artifacts`、`tasks_for_run` 走 `load_all_tasks()` 全量解析、catalog 每分类一次全表扫）是既有形状 → L18 |
| 未处理异常 | N4／N5 已修；其余 4 条「把用户输入问题变成 500 或假告警」→ L19 |
| 资源泄漏 | N3／N4 已修（内存三副本、半份快照）；报告文件与 custom 目录永不删除、`.part` 固定名并发撕半 → L20。上传并发闸（几份同时落盘）N3 只解决了一半 → L17 |
| 阻塞与卡顿 | N3 已修，并把逐块写盘移出事件循环；检视者原文「DB 与文件 IO 全部经 `asyncio.to_thread`，事件循环内未见同步 IO」，本轮改动没有破坏这一条 |
| 日志 | N1（凭据出网）已修，N7（凭据出 API）自查修；变更类操作缺操作人、`cancel` 把 `stop_running()` 的副作用挂在 logger 实参里 → L21 |

越界检查：`git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` **输出为空**，改动全部位于 `pawbench/cpd/acp_remote_eval/**`（含本轮新增的 `redact.py`，28 行）与 `tests/cpd/acp_remote_eval/**`；仓库根只有 `.gitignore`。D23／H3 的「零核心 diff」仍然成立，三份报告各自独立得出同一结论。

代码品质：本轮把 `_without_credentials` 的两份副本合成一份（第三处消费者出现，符合 `rules/code-craft-and-readability.md` 第 5 条「复制到第三处就该抽」），没有新增抽象；`redact.py` 的 docstring 回答的是「为什么不在调用方各写一份」；无注释掉的代码、无裸 TODO、无新增魔法数。行宽：本切片 49 行／16 文件的既有超宽不变（本轮新增代码 0 超宽，报表／数据集／提交三个切片本身也 0 超宽），L10 计数不动。

### 复检与反向验证

6 条严重项逐条对着代码复看过，全量复跑 **523 passed** 无回归。本轮做了一次实测反向验证：把 `cli.py:182` 的 `.name` 守卫改回原样，`test_a_service_that_names_a_path_for_its_file_does_not_choose_where_it_lands` 立刻失败（0.34 s），恢复后全绿——同时它也证明 N1 的匿名 client 仍在（同一用例走下载分支）。其余各条按同一标准写断言，而不是照抄实现：N2 断两个方向都拒且 `kind` 未变，N4 断异常路径两样东西都不在库里（只断 job 行的用例区分不了「回滚」和「从没写」），N5 断提交方读到的**原始异常文本**仍在，N6/N7 断密文在两种视图与两个落盘文件里都不出现且库行不动，N3 断只有路由预检会说的那句话。

一处如实记录的偏差：`test_jobs.py` 那三条「中途失败」用例改用直接给 store 实例赋桩函数（`store.insert_job_with_datasets = refuse_write`），检视者建议改 `monkeypatch.setattr`——本轮没换，靠 conftest 的 function scope 才不会串测试，登记 L23。

### 登记遗留（本轮新增，责任人：anderson）

| # | 位置 | 发现 | 计划 |
|---|---|---|---|
| L17 | `api.py` 上传路由 | 体积闸已生效，并发闸没有：默认线程池 ~32 个上传同时各占一份临时文件，仍可打满磁盘与内存 | M2 收口：包上传单独 `Semaphore(2)` + 落盘前查剩余空间 |
| L18 | `datasets.py:518/718`、`store.py:645`、`reports.py:363/441` | 看板轮询即热路径上的重复全量工作：每分类一次全表扫＋JSON 解码、custom 每次 `describe` 重解析全部 md、报表逐任务一次 `list_artifacts`、`tasks_for_run` 走 `load_all_tasks()` | M3 看板接入前做：分类连接表 + 摘要缓存 + 报表按快照 `resolved_task_ids` 取子集 |
| L19 | `datasets.py:911-930`、`reports.py:684-694/257`、`api.py:119`、`pilot.py:142-152` | 四条把输入问题升格成 500 或假告警：畸形 zip（method 99／成员名冲突／目录名 `*.md`）抛非 DomainError、transcript 只兜 `FileNotFoundError` 且一行坏则整页 500、`unknown_filter_key` 等未入表反而打 `logger.error("unmapped code")`、pilot 在数据集已存在时完全跳过构成校验（`MIN_TASKS=10` 与描述承诺的 15 也不一致） | 逐条补 400/422 映射、`errors="replace"`＋坏行计数、错误码表补全、pilot 每次校验 |
| L20 | `reports.py:280/808-817`、`exchange.py:663`、`datasets.py:485` | 报告文件永不删除（分数每变一次多一个文件，zip 档整份存着被测方文件）；`.part` 名字固定，两个同 fingerprint 的并发请求可撕半已发布的报告；删 dataset 不删 `custom_dir/<id>` | 与 L4 同批做磁盘保留策略；`.part` 改唯一名＋失败 unlink（照 `exchange.py:_stage`）|
| L21 | `datasets.py:289/378/500`、`api.py:430`、`jobs.py:328-360` | 创建／修改／删除只记 dataset_id 不记操作人，`package_unsafe_path` 的安全告警不记肇事成员与 subject；`cancel` 把 `stop_running(job_id)` 写在 `logger.info(extra=...)` 的实参里——副作用挂在日志上，它抛错会把已经成功的取消变成 5xx | 补 subject／文件名（非机密）；副作用先调用、再按结果打日志，`False` 用 warn |
| L22 | `cli.py:447-466/119-128/187-208/336-341` | 文档化的 0/1/2/3 退出码只对 `CliError`／`httpx.HTTPError` 成立：`response.json()` 的 JSONDecodeError、`job["job_id"]` 的 KeyError、写盘 OSError、`--interval` 负值、Ctrl-C 都以 traceback 出门；下载中断或 sha 不符会留半截文件（文案自己写着 "truncated"）；watch 对单次抖动零容忍，`--interval 0` 变无退避忙等；错误文案不带 job id，CI 批量跑多 job 时定位不到哪次请求 | CLI 收尾批一起做（含建议项：`.part` 落盘、顶层兜底分支＋独立崩溃码、interval 下限、错误行带主体）|
| L23 | `datasets.py:232/504/578/886`、`reports.py:633/844`、`test_jobs.py:353+`、`test_cli.py:268/175` | 建议层：`_as_value_set` 在每任务循环里重建；分类名与单次请求分类数无上限；`datasets.py` 直写 SQL 复制了 `store._to_stored`（应由 Store 出 `set_dataset_categories`）；`unpack_package` 混了配额＋前缀＋写盘三件事且 >50 行；`_fingerprint` 收 `job_id` 不用（签名骗人）；zip 条目名用 DB 原文，`a/../b` 能过 `_safe_join` 却把穿越字面写进归档名；`test_jobs` 直接给实例赋桩（建议 `monkeypatch.setattr`）；`test_cli` 两处断言与输出格式强耦合（`"ahead="`、`out.split()[1]`），sha 不符／`report` 缺 `--out`／interval 边界无用例，watch 用例走真实 `time.sleep` | 与 L17/L18 同批改代码，测试断言随 L22 一起收紧 |

第一至三轮的 L1–L15 状态不变；**L16 已由第五轮关闭**（两处 `to_thread` 各有一条探活回归，见 §「复检与反向验证」）。L10 的计数 49 行／16 文件到第五轮仍不动（两轮新增代码 0 超宽），口径见 `test_acp_remote_eval.md` §4.13。

## 复检记录（第五轮：M2 第六批——K2／F2 泄露扫描器 `tools/scan_shared_leakage.py`）

- 检视者：1 个独立 `general-purpose` subagent（会话 `aa410887e3cbf903b`，27 次工具调用，38 分钟）　检视时间：2026-11-10 21:30 前后
- 检视范围：`tests/cpd/acp_remote_eval/tools/scan_shared_leakage.py`（送检时 192 行）+ `support.py`／`test_reports.py`／`test_exchange.py` 的改动；被扫的生产代码 `reports.py`／`exchange.py`／`redact.py`
- 提供的材料：上述文件路径 + 三份规范（`code-craft-and-readability.md`、`logging-quality.md`、`cpd-extension-over-core-edit.md`）+ 五类必查模板。**未提供作者方案说明**，也未告知 §4.13 写了什么
- 检视者自己跑了扫描器（实测退出码、实测命中），报告里的"实测"是它自己的运行结果，不是转述

这一轮和前四轮不同：检的不是服务代码，而是**用来证明服务代码不外发的工具**。工具出错的形态不是崩，是"绿"——所以除了五类必查，另加三问：A 有哪些会出门的文档没被扫、B 哪些断言是永真的、C 词表和生产代码的字段对不对得上。

### 五类必查逐项结论

| # | 类别 | 结论 |
|---|---|---|
| 1 | 性能 | 2 条（P1 一般、P2 建议）：目录遍历与单文件读取都无上限；13 个字段各扫一遍全文 |
| 2 | 未处理异常 | 3 条（P3 **严重**、P4 一般、P5 建议）：打错路径当成"干净"退出 0；只兜 JSONDecodeError；`json.dumps`／`__doc__` 两处不可达但未防 |
| 3 | 资源泄漏 | 类别**无发现**（`read_text` 自关、`@cache` 只 exec 一次）；顺带指出 `support.py` 用 `assert` 当校验（P6） |
| 4 | 阻塞卡顿 | 1 条（P7 一般）：键遍历递归无深度上限。工具不在事件循环内，其余无发现 |
| 5 | 日志 | 2 条（P8 一般、P9 建议）：finding 带 60 字符原文却无位置；跳过的后缀不记录 |
| — | 越界改动 | 无（全部落在 `tests/cpd/`），检视者自己核了这一条 ✔ |

### 发现与处理

| # | 严重度 | 位置 | 发现 | 为什么是问题 | 处理 |
|---|---|---|---|---|---|
| P3 | **严重** | `scan_shared_leakage.py:182` | 路径打错时 `documents_in` 返回空，打印 `0 document(s) scanned, 0 finding(s)` 并 **exit 0**（检视者实测） | 这个工具唯一的用途就是区分"扫过且干净"和"没扫"，把后者渲染成前者等于把门拆了还挂上"已锁"的牌子 | 已修：退出码定成 0=扫过且干净／1=有发现／2=没扫（路径不存在、目录下没有可扫文档、文档数超 `MAX_DOCUMENTS`）。用例 `test_reports.py::test_a_scan_that_never_ran_does_not_report_a_clean_bill` 四条各钉一个码 |
| P8 | 一般 | `:184` | finding 只有 60 字符匹配片段，没有行号／字段路径／所属任务；而片段本身可能就是 rubric 原文 | 两个相反方向的毛病同时犯：定位不到出处（违反 `logging-quality` 第 2 条），又把答案抄进终端和 CI 日志（违反第 3 条） | 已修：三类 finding 一律 `field <名> (line N)`／`key <名> (at tasks[0].rubric_excerpt)`／`marker <型> (line N)`，不带任何被匹配内容。同一用例断 stderr 里有字段名、**没有**片段值（`"tone" not in captured.err`） |
| P1 | 一般 | `:147`+`:169` | 整文件 `read_text` 入内存、`rglob("*")` 无界，指到仓库根会全量读 | 一个"顺手扫一下整个目录"的误用能把这台正在跑评测的机器吃穿内存 | 已修：`MAX_DOCUMENT_BYTES=8 MiB`（超限是一条 `not scanned: …` **finding**，不是静默跳过——"太大看不了"不能读成"干净"）＋`MAX_DOCUMENTS=500`（超限 → exit 2 并指名"point this at a report directory, not a source tree"）。未做深度限制：条数上限已经封住总量，深度再加一层只会让误用变成"看不懂的跳过" |
| P4 | 一般 | `:140-154` | 只捕获 JSONDecodeError；`FileNotFoundError`／`PermissionError` 冒到 `main`，一个不可读文件中断整轮，且 traceback 的 exit 1 与"有发现"同码 | 一个坏文件让剩下 N-1 个没被看，退出码还和"看到答案"无法区分 | 已修：`except OSError` → `unreadable: <异常类型名>`（只带类型名，异常文案可能含绝对路径）；非扫描类失败统一走 2 |
| P10 | 一般（顺带） | `:62` 注释 vs `:65` 正则 | 注释写"不匹配裸 `rubric` 以免误报"，正则 `^#+[^\n]*\brubric\b` 实测命中 `# How to write a rubric`（`grading` 同理） | 任务 prompt 会原样进 shared 报表与 manifest，"教你写评分标准"是合法题面——这就是它自己注释里说要防的喊狼。喊一次狼，下一个人就 `--tier` 掉这次扫描 | 已修：`_HEADING` 只认两种形状——点名判分小节（`rubric excerpt`／`expected behavior`／`answer key`…）或标题**就是**小节名（`## Rubric`）。`test_reports.py:404` 钉住 `## How to write a rubric for the essay` → `[]` |
| A2/A3 | 一般 | `:171`、`test_reports.py:374` | `.jsonl` 不在后缀集（transcript 正是行落盘可下载的原文流）；测试只扫 md/html/json@**shared**，而 `check_format` 只限制 zip，**full 档的三份文件走同一条预签名链接出门，从未按 INTERNAL 扫过** | 报表的全部格式与全部档位都在外发面上，扫一半等于没扫那一半 | 已修：后缀集提为 `DOCUMENT_SUFFIXES` 并加 `.jsonl`；用例改成 2 档位 × 3 格式 + 3 份 payload 全扫，档位与 `FORWARDABLE`／`INTERNAL` 对齐 |
| P14 | 一般 | `test_reports.py:374-378` | md／html 两份文件的断言**名不符实**：破坏 shared 裁剪后它们仍 0 条——渲染器不打印这些键（md 只把 `judge_notes` 改写成 `- judge: …`） | 用例声称"扫的就是那个人会转发的文件"，实际只有 json 文件真随载荷变红；剩下的绿灯是假的 | 已修（承认而非掩饰）：docstring 写明文件半区是**渲染器的回归护栏**，判别力在 json；新增 `test_the_rubric_text_only_ever_reaches_the_full_tier` 用同一 `fmt="json"`、两个档位做双向断言。实测：把 `reports.py:399` 的 `if tier == SENSITIVITY_FULL` 改成 `if True`，3 条用例同时变红（`test_shared_detail_…`、`test_the_rubric_text_…`、`test_the_forwardable_documents_…`），K2 里变红的是 `json report @ shared`，md／html 仍 0 条 |
| P16 | 一般 | `test_reports.py:316-318` | 只断键存在，`rubric_excerpt: None` 也算过——**而本文件所有 fixture 任务都没有 rubric**（`write_task` 没有该段，除 `mail_b` 外都是 checker 判分） | K2 的头号字段从没带着真答案文本走过一次裁剪判断；"hides the rubric"这个用例名描述的是一道题都没有的东西 | 已修：`support.write_task` 加 `rubric=`（写 `## LLM Judge Rubric` 段），`mail_b` 带一句真 rubric，新用例断 full 档载荷与落盘 json 里有这句、shared 档载荷与落盘 json 里连 `polite` 都没有（防"换个键抄出去"） |
| P15 | 一般 | `test_reports.py:352-387` | docstring 称两条 planted 断言是"判别的那一半"，但它们只反证扫描器自身，不反证生产代码 | 两件事都被叫做"判别性"，下一个读的人会把"扫描器还会响"误当成"服务被证明是干净的" | 已修：docstring 重写，明写两半各证什么——干净半区是生产检查（拆裁剪即红），planted 半区是工具自检（词表悄悄失效时干净半区会永远绿） |
| P6 | 一般 | `support.py:352` | `assert spec is not None` 当校验用，`-O` 下整条消失 | 规则要求校验不能靠 `assert`；这里断的是"词表文件加载成功"，它静默失败就是所有 K2/F2 用例失去依据 | 已修：改显式 `raise RuntimeError(...)`，消息带上那个路径本身 |
| P7 | 一般 | `:128`（现 `_paths_of`） | 键遍历递归无深度上限，可被外部捕获文档触发 RecursionError | 深嵌套 JSON 是外部可控制的输入，这是真的 | **不修**，理由：`json.loads` 自己按解释器递归上限解析，能解析出来的文档必然比"每层一帧"的遍历更浅；要防的话得先造出一个 loads 能过而我们不能过的输入。登记 L28 |
| P2 | 建议 | `:101`/`:125` | 13 个字段各扫一遍全文，可合并成一条 alternation | 每文档 13 次全文扫描 | 不修：单文档已被 8 MiB 上限约束，且合并后"命中哪个字段"要靠二次解析找回，finding 的行号语义会变差。登记 L28 |
| P5 | 建议 | `:110`/`:177` | `json.dumps(default=str)` 遇自引用抛 RecursionError；`__doc__.splitlines()[0]` 在 `-OO` 下是 None | 一处未捕获异常、一处 None 进 argparse | 后半已修（`if __doc__ else None`）；前半不修：本工具的载荷只来自磁盘上的 `json.loads` 或测试手写 dict，两条路都不可能构造环 |
| P9 | 建议 | `main` | 不记录被跳过的后缀，读者分不清"安全"和"没看" | 与 P3 同一件事的另一半 | 已修：exit 2 的文案直接列出接受的后缀集与扫过的根目录 |
| A1 | 一般 | `reports.py:838` `_zip` | `.zip` 报告（deflate 打包 full 档 detail + 全部 transcript + 全部产物）不在后缀集，`scan_file` 得 0 条 | 它是本特性体积最大、内容最全的外发文档 | 不修：读 zip 要在扫描器里重造一份解包器（含 zip-slip 判定），而那正是被测方产物进来的地方。已写进模块 docstring 的限制段 → 遗留 L24 |
| A4 | 一般 | `datasets.py:423/466` | dataset 响应体的"不外发判分文本"只靠注释约定，没有任何机检 | builtin 数据集对所有持 token 的人可读，`describe` 返回任务内容 | 登记 L25：先由人判定"builtin 题目的 rubric 对读者是不是答案"，再决定进不进词表 |
| A5 | 建议 | `exchange.py:287 Rebuild.to_payload` | 服务器绝对路径的键叫 `workspace`，词表里只有 `workspace_path`；且 `Rebuild.to_payload` 看不到生产调用方 | 名字不一致时，词表要么漏判要么把 prompt 里的 `workspace` 一词误判 | 登记 L27：要么把键改成 `workspace_path` 并进词表，要么删掉这条无人调用的载荷。加词表项本身不做——会误报 |
| C | 建议 | `scan_shared_leakage.py:59-68` vs `reports.py` | 词表偏多：`judge_prompt` 是函数名不是字段，`grading_code`/`checker_source` 全库无此名（今天永真）；词表偏少：`automated_breakdown`（**shared 也发布**，键来自判分代码里的检查名）、`failure_reason`（可能带检查器文本）、顶层 `error`（可能带 traceback 与路径） | 偏多是占位（注释已说明），偏少是三条真实的外发通道，扫描器表达不了 | 偏多登记 L27（占位须随字段落地转为实项）；偏少登记 L26，需人工判定 `automated_breakdown` 的键名算不算答案泄露 |

### 复检与反向验证

- 反向验证做了两次实测，都是"移除防护 → 看哪几条用例红"，跑完即恢复：
  1. `reports.py:399` 的档位裁剪守卫改成恒真 → `test_shared_detail_shows_the_prompt_and_hides_the_rubric`、`test_the_rubric_text_only_ever_reaches_the_full_tier`、`test_the_forwardable_documents_pass_the_leakage_scan` 三条同时失败（0.60 s），恢复后 `git hash-object` 与原文件一致。
  2. L16 的两处 `to_thread` 各拆一次：`runtime.py:328` 拆 → `test_runtime.py::test_a_store_query_hanging_does_not_hang_the_event_loop` 失败（2.50 s）；`daemon.py:192` 拆 → `test_daemon.py::test_a_startup_reconcile_hanging_does_not_hang_the_event_loop` 失败（2.36 s）。两处都是**判负**而不是挂住：探活的是同循环里的另一个协程，拿不到执行机会就在 2 s 处判 False。恢复后 `test_runtime.py` 25 passed、`test_daemon.py` 21 passed。
- 命令行三态实测（第五轮修复后重跑）：干净单文档 → `0 finding(s)` exit 0；含 planted 的目录 → 3 文档 3 finding、逐条带文件与行号 exit 1；`--tier internal` 扫同一份 → 0 finding（`rubric_excerpt` 属 shared-only，不属答案键）；打错路径 → `nothing was scanned: no such path: …` exit 2。
- 计数：`test_reports.py` 34 → 36（新增退出码用例、rubric 文本用例），`test_runtime.py` 24 → 25，`test_daemon.py` 20 → 21。全量 **529 passed, 1 warning in 15.41s**；扫描器 192 → 290 行，0 超宽；特性文件数仍 **53**（没有新增文件，改的是已有三份测试 + `support.py` + 扫描器本身）。H3 重跑 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` **仍为空输出**。

### 登记遗留（本轮新增，责任人：anderson）

| # | 位置 | 发现 | 期限／处理 |
|---|---|---|---|
| L24 | `scan_shared_leakage.py` docstring、`reports.py:838` | `.zip` 报告扫不了（deflate + 内含 transcript 与产物），rubric  prose 被改写进别的键也扫不了 | 人工签核 = acceptance 遗留 11；机检要在 zip 落地目录上扫，随 L20 磁盘保留策略一起做 |
| L25 | `datasets.py:423/466` | dataset 响应体不在机检范围内，"不外发判分文本"只有注释。要人先判：builtin 题目的 rubric 对读它的成员算不算答案 | M2 出口的人工 review（`review_` R12/R13 那一批）一并判 |
| L26 | `reports.py:380/382/122` | `automated_breakdown`（shared 也发布，键名来自判分代码的检查名）、`failure_reason`（可能带检查器文本）、顶层 `error`（可能带 traceback／绝对路径）是词表表达不了的三条外发通道 | 同上，人判后要么进词表要么在渲染侧收敛；不静默扩表 |
| L27 | `scan_shared_leakage.py:59-68`、`exchange.py:287` | 词表偏多的三项（`judge_prompt` 是函数名、`grading_code`/`checker_source` 不存在）今天永真；`Rebuild.to_payload` 的 `workspace` 键名与词表不一致且疑似无人调用 | 字段落地时把占位转实项；`workspace` 在下一次碰 `exchange.py` 时改名或删载荷 |
| L28 | `scan_shared_leakage.py` `_paths_of`、`_field_findings` | 键遍历无深度上限、13 字段各扫一遍全文（本轮判为不修，理由见 P7/P2） | 若真出现"loads 能过、我们过不了"的输入再改；不预防性加层 |

## 复检记录（第六轮：M2 第八批——出口批 L17／L19／L21 的修复）

- 检视者：1 个独立 `general-purpose` subagent（任务名 `reviewer-l17-l19-l21`，会话 `aed9cbda49e238ddd`，46 次工具调用，约 8 分钟）　检视时间：2026-11-10 23:36 前后
- 检视范围：第八批那份 diff——L17（并发闸 + 落盘前查剩余空间）、L19（四条把输入问题升格成 500／假告警）、L21（日志操作人 + 取消的副作用）改动到的 `api.py`、`datasets.py`、`jobs.py`、`pilot.py`、`reports.py` 与四份测试
- 提供的材料：改动文件 + `git status` 文件清单 + 三份规范（`code-craft-and-readability`、`logging-quality`、`cpd-extension-over-core-edit`）+ 五类必查模板。**未提供作者方案说明**，也未告知 `test_` §4.15 写了什么
- 检视者自己跑了全量（报告第一行就是 `547 passed` 的实测输出），发现 1／3／5 的结论是它在 scratch store 上**另起临时脚本复现**出来的，报告里声明未改动仓库任何文件

这一轮检的不是新功能而是"补遗留"那一批，所以除了五类必查，报告另答三个特别判断：**闸有没有真的界住**、**拒绝之后留下的是不一致还是垃圾**、**本批新增用例里有没有名不符实的断言**。第三条命中最多（发现 8 一次点出三处），而这三处作者自己是看不出来的——用例是我写的，它证的假设和我的假设是同一套。

### 五类必查逐项结论

| # | 类别 | 结论 |
|---|---|---|
| 1 | 性能 | 有发现：#3、#4（无界内存／无界落盘）、#1（重复 IO）。`reports.py:704-733` 每页重读整档属**已注释的取舍**，检视者自己不计 |
| 2 | 未处理异常 | 有发现：#5、#6、#1（拒绝路径未覆盖） |
| 3 | 资源泄漏 | 有发现：#1（孤儿目录）、#4（`.part` 残留）、#7（许可与线程错位） |
| 4 | 阻塞卡顿 | **类别无发现**：事件循环内未见同步 IO，`api.py:1026` 的逐块写与 `datasets.py:410` 都走线程池 |
| 5 | 日志 | **类别无发现**：级别与 `_SECURITY_CODES`／`_CAPACITY_CODES`／`_PACKAGE_GUARD_CODES` 一致，`api.py:500` 对消息做 `repr` + 截断，`auth.py:158` 只打指纹，未见 token／签名链接／请求体入日志，无 `print`／裸 `TODO` |
| — | 越界改动 | 无（`git status` 只有 `pawbench/cpd/`、`tests/cpd/`、`pal_sdd/feat_acp_remote_eval/` 与 `.gitignore`）。**顺带一条**：`.gitignore` 那一行（忽略运行态目录）属本特性范围，但建议与 L10 一样单独提交，不混进特性 commit |

### 发现与处理

| # | 严重度 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| 1 | **严重** | `datasets.py:367-369` | 破坏性落盘早于「还会抛的校验」：`_copy_package` 先 `rmtree`+替换 `custom_dir/<id>`，之后的 `ensure_category` 仍可能抛 `invalid_category_name`。检视者实测同 owner 重传 + `categories=%20`：盘上已是新包（`cust_b.md`），DB 行仍是 `task_ids=['cust_a']`——**数据集从此指向不存在的文件**；换新 id 时更留下无 DB 行的孤儿目录，启动无清扫。363-365 的注释只考虑了 takeover 一种拒绝 | 已修：还会拒绝的两步（takeover 判定、分类名归一）全部提到 `_copy_package` 之前，新增 `_category_name_or_refuse`（staticmethod）让"解析名"和"拒绝"共用同一个答案。用例 `test_a_refused_category_leaves_the_stored_package_and_its_row_alone`（老文件还在、新文件没进来、行没动）与 `test_a_refused_category_does_not_leave_a_package_directory_without_a_row`（新 id 被拒后目录不存在）。**反向**：把名称判定挪回 copy 之后 → 两条同时判红 |
| 2 | 一般 | `api.py:999-1011` | 剩余空间只测 `tempfile.gettempdir()`，而真正落盘处是 `config.datasets.custom_dir`（`/tmp` 是 tmpfs 时这 256 MB 直接吃内存），docstring 却声称保护的是"DB/转录/报告共用的卷"；且只按 `Content-Length` 查一次，没算解包的第二份和并发 2 份 | 已修前一半 + 说清：**两卷各查一次**，缺在的包目录经 `_existing_parent` 退到最近的真实目录（对不存在的路径问 `disk_usage` 会抛，而这一抛读起来像服务坏了），docstring 改写成"这个请求各花掉它们一次"。用例 `test_a_full_package_volume_is_refused_though_the_temp_directory_is_empty` 断两次 `disk_usage` 分别落在临时卷与包卷、且告警文案点的是包卷。**后一半（额度按 `(archive + 解包) × MAX_CONCURRENT` 计）不修** → L29 |
| 3 | 一般 | `api.py:389-421`、`exchange.py:480-483`、`api.py:961` | 绕过闸的落盘入口：artifact PUT 不占 semaphore、不查空间，`_read_body` 把整份 body 缓在内存再写两份盘，并发只受线程池宽度约束；`_json_object` 用 `request.body()`，**无任何大小上限** | JSON 那一半已修：`MAX_JSON_BODY_BYTES = 1 MiB`，`_json_object` 改走带上限的 `_read_body`（新增码 `body_too_large` → 413 入 `_CONTROL_STATUS`，于是 `test_every_control_plane_code_promises_a_status` 一并盯住它），并把 `except Exception` 收成 `except (ValueError, RecursionError)`——`json` 按解释器栈下探文档深度，全是左括号的正文是合法语法加上爆深度。两条用例，各对应一处反向红。**artifact PUT 那一半** → L30 |
| 4 | 一般 | `reports.py:307-312/887-916/875-884` | `report?format=zip` 在 `io.BytesIO` 里拼整包再 `getvalue()`（**两份全量内存**），大小由已存 artifacts 决定、不受 `MAX_PACKAGE_BYTES` 与闸约束；`_write` 失败时 `.{name}.part` 不删 | 不修，整条并入 **L20**（那行本来就登记了 `.part` 唯一名 + 失败 unlink、报告文件永不删除）；闸的覆盖面那一半并入 L30。**判为不修的理由不是"不会发生"，是"改它要连磁盘保留策略一起改"**：`ZipFile(path)` 直写目标意味着渲染失败会留下半份 `.part`，而那正是 L20 要一并定的事 |
| 5 | 一般 | `reports.py:717-734` | `_read_window` 只把 `open()` 的 `OSError` 归为 `unreadable`，迭代中途的 `OSError` 冒到没有 handler 的路由 → 500，与它自己"一个状态说清两种读不到"的说法不符；无测试覆盖 | 已修：整个走档循环包进 `except OSError` → `unreadable`。用例 `test_a_transcript_that_fails_mid_read_is_unreadable_and_not_a_half_page`（`monkeypatch` 换 `Path.open`，只对 `transcript.jsonl` 递出一个读到第二行就抛的对象）。**反向**：守卫拆成恒真/恒假 → 判红 |
| 6 | 一般 | `reports.py:753-759` | `_timeline_events` 只捕 `ValueError`，`json.loads` 对超深嵌套行抛 `RecursionError`（检视者已验证它不是 `ValueError` 子类）→ 一页坏数据把 200 行好内容打成 500 | 已修：一并计入 `damaged`。用例 `test_a_line_that_is_too_deep_to_parse_costs_a_count_and_not_the_page` 用 `b"[" * 50000`——**门槛是量出来的**：5000 层能解析、20000 层抛。**"`_read_window` 加单行长度上限"那一半不修** → L31 |
| 7 | 一般 | `api.py:671-684` | 闸圈的是协程不是线程：`to_thread` 不可取消，客户端断连时 `async with` 先释放许可、解包线程仍在写 staging，最坏情况上界失效；全路径无任何超时 | 不修 → **L29**（与 #2 的额度那一半同批：要么许可随线程结束才释放，要么闸内 `asyncio.timeout`，这是一个取舍不是补断言） |
| 8 | 建议 | `test_datasets_api.py:623-653/708/745`、`api.py:317/473`、`datasets.py:167/1049/1125` | 三处**名不符实的断言**：峰值计数器取自 `register_custom_archive`，看不到流式阶段，把 `async with` 缩到只包解包仍全绿；`peak == MAX_CONCURRENT_PACKAGE_UPLOADS` 是常量自比，2 改成 32 也绿；`volumes == [Path(tempfile.gettempdir())]` 把"测错卷"钉成期望。另：两个异常 handler 同名 `_refuse`（一个数据面一个控制面），三处函数内 `import` 无"为什么"注释 | 全部已处理：计数器改包住 `api_module._stream_body_to_file`（运行期经模块属性查找才换得动），峰值同时断 `== 常量` 与 `< 3`（绝对上界，改常量为 32 会红）；`volumes` 断言改成"两只卷分别是临时卷与包卷"；两个 handler 改名 `_refuse_exchange`／`_refuse_service`；`hashlib`／`json`／`shutil` 提到模块级——三条都是 stdlib，**不存在"避免循环依赖"这个理由**，所以选了改名而不是补一条编造的注释 |

### 三个特别判断的处置

1. **"没有界住"**——闸 + 空间检查只覆盖 `POST /v1/datasets/packages` 一条路径，最坏情况不是 `api.py:246` 承诺的"两个包"这个数。**部分采纳**：JSON 路线本轮带上限了（#3），包卷测对了（#2），但 artifact PUT／zip 报告两个写盘入口仍在闸外（L30），额度仍按单份包计（L29）。`MAX_CONCURRENT_PACKAGE_UPLOADS` 的注释承诺"最坏情况是一个可以说出口的数字"，在 L30 关掉之前这个承诺只对 package 路由成立——已在注释里点名是哪条路由，不留全称命题。
2. **"留下文件与数据库不一致，而不是垃圾"**——已修（#1）。这一条是本轮唯一的严重项，且是检视者独立复现的：547 项全绿里跑了一整轮。
3. **"有（用例名不符实）"**——三条全改（#8）。

### 复检与反向验证

- `/tmp/reverse_round6.py` 八条变异：BASELINE 9 passed 全绿 → **8/8 判红、零幸存者**，每条 0.34–0.74 s，`finally` 恢复后逐文件 sha256 与原文件一致。其中三条改的是**位置**而不是有无（闸往里挪一格、只测一卷、copy 之后才判名），因为本轮的失败形态正是"修复在，但没在起作用的那一步"——这类变异第八批那三份脚本证不了。
- `/tmp/reverse_l17.py` 本轮重跑过一次：它原来的 `ROOM_FIX`/`GATE_FIX` 锚点已被 #2 的两卷改写顶掉，脚本如实打印两条 `SKIP` 并把跳过算进幸存者。**锚点失效不会静默，但也不会自己修好**——修正锚点后 3/3 判红（BASELINE 3 passed）。反向脚本与它盯的代码是同一份需要维护的资产，改代码的人要顺手改锚点。
- 收口重跑：全量 **555 passed, 1 warning in 15.98s**（547 → 555，+8：`test_datasets.py` +2、`test_reports.py` +2、`test_datasets_api.py` +2、`test_control_api.py` +2）；H3 过滤 `cpd/` 后**仍为空输出**；超宽普查仍 **49 行／16 文件**，本批新增 0 行（`api.py` 最长 100 字符，正好在 `line-length = 100` 上界内）。
- **第四轮登记的 L17／L19／L21 三条遗留本轮关闭**（证据见 `test_` §4.15 的三组反向实测 9/9、5/5、3/3 与上面这轮 8/8）。严重项：**发现 1 已修并各带判别性用例，本轮无未修严重项**，满足"严重项未修不许 commit"。

### 登记遗留（本轮新增，责任人：anderson）

| # | 位置 | 发现 | 期限／处理 |
|---|---|---|---|
| L29 | `api.py:671-684`（闸）、`api.py:_stream_body_to_file` 的空间额度 | 闸的两处如实边界：① 许可随协程释放，`asyncio.to_thread` 的解包不可取消——客户端断连时最坏情况比"两个包"多；全路径无超时。② 剩余空间按**单份声明体积**查两卷，未算解包的第二份 × 并发数 | 与 L30 同批（都要先定"闸内动作的边界是什么"这个取舍），M3 之前——插件看板会再加写盘入口 |
| L30 | `api.py:389-421`（artifact PUT）、`reports.py:887-916`（zip 报告） | 另两个把调用方字节写盘＋占内存的入口在容量闸外：PUT 不占 semaphore、不查空间（`_read_body` 全量缓存在内存再由 `_stage`+`os.replace` 写两份），zip 在 `io.BytesIO` 里两份全量、大小由已存产物决定；`_write` 失败时 `.part` 残留 | 与 **L20** 的磁盘保留策略同批做（`ZipFile(path)` 直写 `.part` 要先定失败与并发语义）；`MAX_CONCURRENT_PACKAGE_UPLOADS` 注释里"最坏情况可以说出口"这句在 L30 关掉前只指 package 路由 |
| L31 | `reports.py:_read_window` | 走档按行读，没有单行长度上限：一条超长的 transcript 行会整条进内存 | 不预防性加上限（当前来源是服务自己写的 ACP 事件行，长度由判分机而非调用方决定）；下次碰 `reports.py` 时连同 `damaged_events` 的语义一起定 |

## 复检记录（第七轮：M2 第十批——关闭 L18 的四类重复全量工作）

- 检视者：1 个独立 `general-purpose` subagent（任务名 `reviewer-l18`）　检视时间：2026-11-10 16:41 UTC
- 检视范围：第十批那份 diff——`store.py`(834) 的 `category_dataset_counts`、`datasets.py`(1194) 的 `_index`／`_tasks_dir`／`_task_file_signature`／`tasks_for_run`／`list_categories`、`reports.py`(1024) 的 `_artifacts_by_task`／`job_detail`／`_zip`，加新用例 `test_datasets.py:657+`、`test_reports.py:304-322/396-424` 与 `/tmp/reverse_round7.py`（只读、未运行）
- 提供的材料：改动文件 + 行号区间 + 三份规范（`code-craft-and-readability`、`logging-quality`、`cpd-extension-over-core-edit`）+ 五类必查模板 + 测试命令。**未提供作者方案说明**，也未告知 `test_` §4.17 写了什么
- 检视者独立复核做了什么：自己跑全量（报告第一行 `560 passed / 17.19s`）；在 `/tmp` 另写两份只读探针复现发现 1／3／4——`probe_race7.py`（300 轮 × 6 线程 = **1800 次并发 describe，errors=`KeyError:'warm_2'×4, 'warm_3'×1, 'warm_1'×1`**）、`probe_round7.py`（`{'office tooling': 2}`；md 报告 `{bodies:2, job_tasks:3}` vs detail `1/1`）；结束后 `git status` 与检视前一致，仓库未被改动

这一轮检的是"把重复工作去掉"的那一批，而它检出来的三条**都不是重复工作本身**：一条是缓存的并发形态（第十批的五条用例全在单线程里跑），一条是签名失效的覆盖面（只测了 custom 包那一支），一条是渲染路径上还没收敛的第二遍全量解析。检视者对反向脚本的推演也如实说了边界——七条变异"逐一推演确会判红"，但"只覆盖已写用例的 5 处优化，发现 1/2/3 结构性不在射程内"。

### 五类必查逐项结论

| # | 类别 | 结论 |
|---|---|---|
| 1 | 性能 | 有发现：#3（报告面两遍全量 `_bodies`）、#4（计数按出现次数）、#6（zip 整包两份内存） |
| 2 | 未处理异常 | 有发现：#1（缓存淘汰竞态，看板侧是 500、报表侧被 `reports.py:485` 的宽 `except Exception` 降级成静默缺字段）、#5（单文件解析异常升格成整单失败） |
| 3 | 资源泄漏 | **缓存有界 ✓、DB／文件句柄均 `with` ✓**，仅 #6 的 `.part` 残留（已登记） |
| 4 | 阻塞卡顿 | **类别无发现**：全部经 `to_thread`，transcript 流式读，zip 在 worker 线程内 |
| 5 | 日志 | **类别无发现**：无 `print`／裸 `TODO`，新增路径未打噪音日志；#2 的"静默跳过"作为日志缺口并入其改法 |
| — | 越界改动 | 无：`git status --porcelain` 只有 `.gitignore`（根目录，非 `pawbench/` 核心）+ 未跟踪 `pal_sdd`、`pawbench/cpd`、`tests/cpd`。等价性另核：产物分桶保序（`ORDER BY task_id, path`）与分档字段等价；全仓仅 `datasets.py` 两处写 `datasets` 且都经规范化 |

### 发现与处理

| # | 严重度 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| 1 | **严重** | `datasets.py:796-797`（原） | `_indexes` 的「判满 → 挑最旧 key → pop → 写」四步没有串行化：路由全走 `asyncio.to_thread`（≤32 线程），两线程会对同一个 key 各 `pop` 一次，第二个抛 `KeyError`。检视者 1800 次并发 describe 实测 6 次；看板轮询表现为 500，**更坏的是 `reports.py:485` 的 `except Exception` 把它降级成 warning，报告静默丢 labels/prompt——数据错误而不是故障** | 已修（`datasets.py:264/819/826`）：解析留在锁外（两个 worker 同时 miss 付的是重复解析，不是排队），「命中判定」与「写回 + 淘汰」各自进 `threading.Lock`。**建议的 `popitem(last=False)` 未采纳**：普通 dict 已是插入序，锁内它与 `pop(next(iter()))` 等价，换了不改变任何行为，而现形的断言锚在"移除"这一步上——换写法等于用一条判别性用例换一条同形状的。**未采纳的第三条**：`_indexes` 是 `DatasetService` 实例态、`Store` 有 `self._lock` 而它没有，这条边界已在 `__init__` 注释里点名。用例 `test_two_workers_reaching_a_full_cache_do_not_evict_the_same_key`（测试侧 `SlowEvictDict.pop` 先睡再转真 `pop`，让竞态成为这一轮的事实而不是线程运气）。**反向**：整体拆锁、只留读锁（写半边仍在锁外）两条变异各判红；实测失败信息 `KeyError('ds_0')`；检视者的 `probe_race7.py` 重跑 → 1800 次 `errors=none` |
| 2 | 一般 | `datasets.py:788` 与 `199-203`（原） | 签名失效只覆盖 custom 包，`BuiltinCatalog._tasks` 永不过期：进程存活期内更新 `data/pawbench-v1.0`，内置视图的 `describe`／`tasks_for_run` 仍用旧索引；文件改名或删除时 `is_file()` 静默跳过 → 任务少跑且无日志 | **不修** → **L32**。理由：给 builtin 一支加签名就等于承诺"语料可以在进程活着的时候换"，而这条特性里语料是随包发的只读目录，M4 的打标流程才会真改它；改它还要先定"改名算删除还是算新增"的口径 |
| 3 | 一般 | `reports.py:321→381→186` | 报告面"一次一遍"没做完：一次 md/html 渲染 = **2 遍 `_bodies`（全量任务体解析）+ 3 次 `list_job_tasks`**（检视者实测计数），而 `job_detail` 单项是 1/1；且 `_bodies` 按数据集全量而非本次 `resolved_task_ids` 解析 | **不修** → **L33**。改法是 `results(job_id, *, rows=None, bodies=None)` 让 `_render` 复用 job_detail 已算好的 bodies——这是一次接口形状变更，混在"关遗留"批里会让 diff 失去可读性；本轮重跑探针确认数字未变（`{bodies:2, job_tasks:3}`） |
| 4 | 一般 | `store.py:637-639`（+`datasets.py:289`） | 一行 `categories` 里重复同名分类被重复计数：`POST /v1/datasets {categories:["Office Tooling","office tooling"]}` 实测 `dataset_count=2`（实际 1 个数据集），看板与 `delete_category` 的引用数同时错——**同一个数字既给人看又用来判"还能不能删"** | 已修**两半**（检视者要求的两半都在内）：读侧每行 `dict.fromkeys(...)`（`store.py:641`），写侧存库前去重（`datasets.py:297` 与 `396`，后者在 `_copy_package` 之前，与第六轮严重项的顺序约束一致）。用例 `test_a_category_filed_on_one_dataset_twice_is_one_dataset`：先经公开创建路径断存下的就是 `["field kit"]`，再直接落一条旧格式的重复行（**已经入库的行不会被重写，所以读侧必须自己判对**）断 `dataset_count==1` 与拒绝消息里的数字。**反向**：读侧、写侧各一条变异分别判红；探针重跑 → `{'office tooling': 1}`、存库列 `['office tooling']` |
| 5 | 建议 | `datasets.py:513`（原） | `load_task` 直抛，而旧 `load_all_tasks()` 对单文件异常是跳过：索引与磁盘不一致（签名相同但内容已坏）时，runner 从"少一个任务"变成整单失败 | 已修（`datasets.py:522-534`）：单文件 `try/except ValueError` + `logger.warning` 带 `dataset_id`／`task_id`／`reason`，保持原语义。**这条是第十批自己引入的行为变更且当时未登记**，故按修处理而不是遗留。用例 `test_an_unparseable_task_file_costs_its_task_and_not_the_run`（先 `describe` 把索引烘热，再换上一个对 `cust_b` 抛 `ValueError` 的 loader——这样"索引说有、读的时候坏"才是被测的那一步，否则 `load_all_tasks` 自己就把文件跳过了）。**反向**：改回直抛 → 判红，且日志断言同步判红 |
| 6 | 建议 | `reports.py:932-949/898-907` | `BytesIO.getvalue()` 整包复制（文档自陈 64 MB zip，一次请求约 2× 峰值内存）；`_write` 失败残留 `.part` | 不修，与第六轮 #4 同一条：`.part` 与保留策略在 **L20**，闸与内存上界在 **L30**。本轮未重复登记，避免同一件事两个编号 |

### 复检与反向验证

- `/tmp/reverse_round8.py` 五条变异（严重项两条：整体无锁、只锁读半边；#4 两条：读侧、写侧；#5 一条）：BASELINE 3 passed → **5/5 判红、零幸存者**，`finally` 恢复后 sha256 一致。**"只锁读半边"这条是本轮新增的变异类型**——它证的不是"有没有锁"而是"锁在起作用的哪一步"，与第六轮 #8 那三条同类。
- 锚点维护如实记录：第十批之后 `_index` 与 `tasks_for_run` 的文本被本轮改写，`/tmp/reverse_round7.py` 的四条锚点（`CACHE_ON`／`SIGNATURE_CHECK`／`CACHE_BOUND`／`SUBSET_READ`）与 `/tmp/reverse_round6.py` 的一条（`NAMES_BEFORE_COPY`）已同步修正；三条脚本本轮各重跑一遍 → **7/7、8/8 全判红、零幸存者**。改代码的人要顺手改锚点，这条边界从第六轮起一直成立。
- 收口重跑：全量 **563 passed, 1 warning in 16.03s**（560 → 563，+3 全在 `test_datasets.py`）；H3 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 过滤 `cpd/` 后**仍为空输出**；超宽普查仍 **49 行／16 文件**，本批新增 0 行；`.py` 文件数 **50**（后端 26／测试 24）。
- 严重项结论：**发现 1 已修并带判别性用例与检视者自己的探针双重确认，本轮无未修严重项**，满足"严重项未修不许 commit"。三条不修的（#2/#3/#6）各有一条遗留与口径。

### 登记遗留（本轮新增，责任人：anderson）

| # | 位置 | 发现 | 期限／处理 |
|---|---|---|---|
| L32 | `datasets.py`（`BuiltinCatalog._tasks` 无失效路径）、`tasks_for_run` 的 `is_file()` 跳过 | 索引失效只覆盖 custom 包：进程存活期内替换 `data/pawbench-v1.0` 不会反映到内置视图；内置语料里缺文件是静默跳过而不是告警 | **已关闭（随第十二批，第八轮发现 2 与发现 4）**：`BuiltinCatalog` 改持一个 `_index_pair = (signature, summaries)`，每次读先比签名；消失的 id 按 run 聚合成一条 warning。原来要"先定口径"的那一问由实现回答：**索引按目录重建，改名 = 删除 + 新增**，不做"改名追踪"。用例 `test_a_corpus_edit_reaches_the_view_that_was_already_saved` + `test_a_task_that_vanished_from_disk_is_reported_once_per_run` |
| L33 | `reports.py:321→381→186`、`_bodies`(470-495)、`tasks_for_run`(507-541) | 一次 md/html 渲染付两遍全量 `_bodies` + 三次 `list_job_tasks`，且 `_bodies` 按数据集而非本次 `resolved_task_ids` 解析（第七轮探针实测 `2/3`，detail 路线 `1/1`）。**第八轮在真实语料（150 任务）上补测的三个数**：`tasks_for_run` = 0.141s／0.138s 每次调用；`task_detail` 渲染 1 个任务解析 **40 个**；`_render(md/html)` 重算 `_bodies` = **+80 次 `load_task`**；3 次 full `job_detail` = **120 次**解析 | M3 看板接入后与 L20 同批：`results()` 接受已算好的 rows/bodies 是接口变更，单独一个 diff 做。**改它时必须一起改的一条断言**：`test_job_detail_reads_the_artifact_rows_once_for_a_whole_job`（用例 396）现在把"zip 那条路再读一次产物行"写进了断言，它记的是当前形状，不是对外承诺 |
| L34 | `reports.py:485` | 报表侧取数据集来源时 `except Exception` 全吞：注释说"数据集被改走是缺口不是错误"，这个判断本身成立，但它同时把任何读侧故障（本轮的竞态是第一例）降级成一条 warning，报告照常出、字段静默缺 | 与 L32 同批定：**先定"哪些异常算缺口、哪些必须让报告失败"**，再把它收成具体类型；只加日志不够，因为读者看不出这一份报告少了什么。**第八轮发现 5 复核的是同一处**（并点名它会把 sqlite `OperationalError`／`PermissionError` 一起吞掉），未重复编号；L32 已关闭，故这条现在与 L33 同批 |

## 轮外自查（第八轮等待期间，2026-11-10 17:13 UTC）

发现方式不是检视，是**为 commit 做的那一遍"会不会把凭据一起提交上去"**：对特性目录里可能出现的每一个运行时路径逐条 `git check-ignore -v`，并用 `parse_config` 实测两种 config 输入下这些路径到底落在哪。因为不在第八轮的射程里（`config.py` 与 `.gitignore` 都不是它的材料），单记一节，不混进第八轮的发现表。

实测（`base` = `pawbench/cpd/acp_remote_eval/service/`，即 config 文件所在目录）：

| config 输入 | `state_db` | `custom_dir` | `exchange_dir` | `builtin_dir` |
|---|---|---|---|---|
| 照 `config.example.yaml` 写 | `service/runtime/state.db` | `runtime/datasets` | `runtime/exchange` | 仓库根 `data/pawbench-v1.0` |
| **省略这三个键** | `service/service/state.db` | `service/service/datasets` | `service/service/exchange` | `service/data/pawbench-v1.0` |

三条后果，按严重性排：

1. **`.gitignore` 只盖住了 `runtime/` 那一半。** `config.py:214/266/267/277` 的 fallback 常量写作 `service/state.db`、`data/pawbench-v1.0` 这种"相对仓库根"的形状，而 `_path` 锚的是 config 文件所在目录——省略键的人于是把 sqlite（**含 run token 与 subject 端点 URL**）写进 `pawbench/cpd/**`，而这一批的默认提交动作恰好是 `git add pawbench/cpd`。
2. **少写 `datasets.builtin_dir` 时内置语料解析到 `service/data/pawbench-v1.0`**，`describe` 只会报语料为空。这不是安全问题，是"默认值锚点与文档锚点不是同一个"的功能问题——同一条根因的第二种表现。
3. **`config.yaml` 本身没被忽略**，而 `README.md:50` 写着它被忽略（那是放 `public_base_url`、allowlist 路径与 judge key 的文件）。

已做（只动 `.gitignore`，代码零改动）：补三条规则——`service/service/`、`service/data/`、`service/config.yaml`。复核：上面四条实测路径逐条 `check-ignore` 命中（分别由 32/28/28/29 行盖住）；`git ls-files -c | git check-ignore --stdin` **空输出**，即没有已跟踪文件被新规则盖住；特性文件计数 **29 / 24 / 12** 未变；H3 `git diff --name-only main -- …` 过滤 `cpd/` 后仍为空。规则里带了一段"为什么"的注释，否则下一个人会把 `service/service/` 当成手误删掉。

不修的部分登记为 **L35**（下表），因为它要改的是 `config.py` 的对外默认值——属行为变更，得配一条"省略键时 `state_db` 就在 `runtime/` 里"的用例，而且不能与本批 563 项基线混跑（同一轮里既改默认锚点又加用例，红了分不清是哪件事）。

| # | 位置 | 发现 | 期限／处理 |
|---|---|---|---|
| L35 | `config.py:214`／`266`／`267`／`277` 的 fallback 常量、`README.md:50` | 默认值的锚点是"相对仓库根"，`_path` 的锚是"相对 config 文件目录"：省略 `state_db`／`custom_dir`／`exchange_dir`／`builtin_dir` 时状态与语料落到 `service/service/…` 与 `service/data/…`。第 1 条后果已由 `.gitignore` 兜住（不会误提交），第 2 条（语料解析为空）仍未修 | ~~M3 看板接入前——那是第一次真实本地长跑。改法是把四个 fallback 写成相对 config 目录（`runtime/…`、builtin 用 `../../../../data/pawbench-v1.0`，与 example 同形），配一条"省略键 → 与 example 同路径"的用例；同时把 `README.md:50` 那句改成规则实际覆盖的范围~~ → **已随第十三批关闭（2026-11-11）**，改法与登记的完全一致：四个 fallback 改成 `runtime/state.db`／`runtime/datasets`／`runtime/exchange`／`../../../../data/pawbench-v1.0`，"为什么"写进 `_path` 的 docstring（锚是 config 目录不是仓库根；仓库根形状的默认会把持有 run token 与被测端点 URL 的 sqlite 放进 `pawbench/cpd/**`，而那正是 `git add` 会捞到的子树）与 `builtin_dir` 的调用点（四级数的是包在仓库根下的深度）。两条用例各钉一半：`test_omitting_the_paths_lands_where_the_example_says` 断三个运行时路径落在 `tmp_path/"runtime"` **且逐个断 `not path.is_relative_to(<repo>/pawbench)`**（判据不是"落在这儿对不对"而是"绝不落在会被提交的子树里"），`test_the_omitted_corpus_default_is_the_shipped_one` 锚在真 config 目录上断"省略 == example 的那条 + `is_dir()`"，把"四级"这个数字钉住。反向 `reverse_checks/reverse_round10.py`（`/tmp` 那份逐字节归档）四条变异各把一个默认值放回旧形状：BASELINE **27 passed** → **4/4 判红、零幸存者**，`finally` 恢复后 sha256 一致；同批重跑 round9／round7／round6／round8 → **11/11、7/7、8/8、5/5，无一条 `SKIP`**。`README.md:50` 那句已改写（省略这四个键得到的就是 example 展示的同样四个位置；那两条额外规则覆盖的是手写相对路径可能产生的形状）。**另有一处随批修掉的假话**：`.gitignore` 里那两条规则的注释原本写着"默认值落在 `service/service/` 而不是 `runtime/`"，L35 关掉后它成了错的，改成"手写相对路径仍可能产生的两种形状"——留着假话比没有注释更贵。两条既有断言也被这批顶掉：`test_config.py:65`（原来断 `service/state.db` 与 `data/pawbench-v1.0`）与 `test_daemon.py:422`（`write_config` 省略 `state_db`，原断 `parent == tmp_path/"service"`）；后者是**跑全量才暴露的**（`1 failed, 571 passed`），说明旧默认值确实被用例固化过。**这条也是"文档说的和管的是不是同一个数字"这一类**，与第八批 pilot `MIN_TASKS` 那格同族 |
| L36 | ~~`test_pilot.py`（全部跑合成目录）~~、`service/pilot.py:58` 的 `PILOT_TASK_IDS` | **本条登记时的前提是错的，第十三批核实后作废（2026-11-11）**。原文说"构成门槛从来没在真实 `data/pawbench-v1.0` 上被自动化跑过、套件里没有对应用例"——实际 `test_pilot.py` 顶部就写着 `REAL_CATALOGUE = REPO_ROOT / "data" / "pawbench-v1.0"`，**四条用例直接读它**：`test_the_shipped_seed_passes_its_own_gate`(:86) 断 `missing == []`、`len(chosen) == 15`、`composition_gaps(chosen, missing_ids=missing) == []`（就是本条要求补的那两个断言）；`test_the_seed_covers_the_fixture_kinds_its_comments_claim`(:101) 在真 front matter 上断 `{"xlsx","png","pdf"} <= kinds` 与 `attached >= MIN_ATTACHMENT_TASKS`；`test_the_gate_is_the_number_the_seed_advertises`(:144) 断 `len(chosen) == MIN_TASKS`；`test_the_seed_carries_everything_a_submission_needs`(:119) 对真语料 seed 后断 `tasks_for_run` 解析出全部 15 个 id。语料换版本或改掉 15 个 id 里任何一个，这几条**会红**，不是"570 项仍全绿" | **作废，不加用例**。另一条要求"不存在即 skip"也不做：`data/pawbench-v1.0` 是**已跟踪的 1185 个文件**（`git ls-files` 实测），任何一份 clone 里它都在，为它加 skip 是给不会发生的状态写兜底。**要留的是这条教训**：§4.19 那一次手工探针与 L36 的登记都没有先 `grep REAL_CATALOGUE`，于是把"我没找到"写成了"套件里没有"——登记遗留之前要先搜一遍它声称缺的东西。**另附一条不是缺陷的观察**：`pilot_v1` 的 `categories` 为空，M3 看板按分类浏览时 pilot 不会出现——归入遗留 4，但它是数据决定（挂哪些分类由评测负责人定），**不占原型三问的名额**，`design_` §12 已单列 |

## 复检记录（第八轮：M2 第十批＋第十一批——作为同一个 commit 出门的配对 diff）

- 检视者：1 个独立 `general-purpose` subagent（任务名 `reviewer-pair10-11`，后台运行）　检视时间：2026-11-10 17:07 UTC 发起
- 检视范围：第十批＋第十一批合起来的那份 diff——`store.py` 的 `list_categories`(622)／`category_dataset_counts`(628-644)／`datasets_with_category`(645)；`datasets.py` 的 `DatasetService.__init__`（`_indexes`／`_index_lock`）／`create_builtin_view`／custom 注册与编辑路径的分类归一／`describe`(488)／`tasks_for_run`(507-535)／`list_categories`(603)／`_index`(813-831)／`_tasks_dir`／`_task_file_signature`(1144)；`reports.py` 的 `job_detail`(113)／`_bodies`(470)／`_artifacts_by_task`(910)／`_zip`(924)；用例 `test_datasets.py` 695／744／798／852／883 与 `test_reports.py` 304／396
- 提供的材料：改动文件 + 行号区间 + 三份规范 + 五类必查模板 + 测试命令，并**明确要求整份文件都读**。**未提供作者方案说明**，也未告知 `test_` §4.17／§4.18 写了什么
- 特别要求（这一轮新增的两问）：① 两批**合在一起**是否自洽——新增的守卫/锁是否覆盖了它所保护状态的全部读写路径，被优化掉的读取路径与仍在的读取路径语义是否一致；② 这些改动的用例是否在代码**实际被调用的执行模型**下跑过，有没有"断言看着在证 A、实际证的是 B"的用例
- 检视者独立复核做了什么：自己跑全量（报告第一行 **563 passed / 17.87s**）；在 `/tmp` 另写五份脚本复现发现——`rv_a_lock.py`（把 `_index_lock` 换成空上下文 → `[('KeyError', "'ds_0'")]`；带锁 → `([], 32)`）、`rv_bcd.py`、`rv_de.py`、`rv_gh.py`、`rv_real.py`（真实语料 150 任务上的计数与耗时：`tasks_for_run` = 0.141s／0.138s 每次调用、`task_detail` 渲染 1 个任务解析 40 个、`_render(md)` +80 次 `load_task`、32MiB 产物 → zip 32.0MiB、RSS 峰值 +24MiB）；结束后 `git status` 与检视前一致，**仓库零改动**

这一轮的两问都问出了东西。第①问的答案是"不自洽"：第十一批给 custom 路径加的签名失效守卫，`builtin_view` 那条**提前返回**绕过去了（发现 2）；写侧去重加在创建路径上，`assign_categories` 那条写路径没覆盖（发现 7）。第②问的答案是三条用例有问题：798 的锁断言确实成立、但同一用例里的缓存长度断言在两种实现下都是 32（不起判别作用）；883 属于"看着证 A 实为 B"；#1 与 #2 两条**根本没有用例覆盖**。

### 五类必查逐项结论

| # | 类别 | 结论（检视者原文口径） |
|---|---|---|
| 1 | 性能 | 有发现：#3（正文 bodies 无缓存，被消除的重复全量工作在这条路上还留着）、#6（zip 整包两份内存）、#8（`_render` 重算 `_bodies`）、#10（为一个数字做整表读+解码）。另核：`artifacts`／`job_tasks` 查询走 PK 前缀，**无缺索引**；无正则回溯风险 |
| 2 | 未处理异常 | 有发现：#5（`except Exception` 把 sqlite `OperationalError`／`PermissionError` 一起吞成"这个数据集缺了"）、#4（索引与磁盘不一致的分支不记日志）。另核：`unpack_package`／`_write_capped`／`_read_window` 的异常路径都用 `with` 或 `finally` 收口，**未发现吞异常后返回成功** |
| 3 | 资源泄漏 | **无严重发现**。已核对：`_indexes` 的全部读写（819／826-829）在锁内、`with` 释放；缓存有界（33 个数据集后 `len==32`，实测复现）；zipfile／句柄在 `with` 内；staging 由 `TemporaryDirectory` 清理；`upload` 在 `finally` unlink。建议级一条：`delete_dataset` 不失效 `_indexes` |
| 4 | 阻塞卡顿 | 有发现：#1（并发渲染互相截断）、#6（整包进内存）。另核：所有 store／datasets／reports 调用确认经 `asyncio.to_thread`（`api.py:540-874`），`DatasetService` 在 `daemon.py:125` 单例构造——**线程模型成立** |
| 5 | 日志 | **无严重发现**：级别与主体（`dataset_id`／`job_id`／`task_id`）齐备，无 `print` 残留、无敏感字段。仅两处：#4 的静默分支，以及 `tasks_for_run` 循环内 warning（每次报表轮询都可能重放） |
| — | 越界改动 | 无：改动全在 `pawbench/cpd/acp_remote_eval/` 与 `tests/cpd/`，`.gitignore` 三行是运行时状态与操作员配置，**未越界直改核心** |

### 发现与处理

| # | 严重度 | 位置 | 发现（检视者实测） | 处理 |
|---|---|---|---|---|
| 1 | **严重** | `reports.py:898-907` `_write` | 临时名固定 `.{name}.part`，并发渲染互相截断：两线程同写一名 → `errors=['FileNotFoundError(2,...)']`，最终 4,000,028 字节且 `JSONDecodeError`。`report()` 的 sha256／size／链接都取自这个坏文件，于是它被当"已缓存的正确报表"**长期服务** | 已修**三段**（第十二批）：① 暂存名换成 `.{name}.{secrets.token_hex(8)}.part`（沿用本特性 `exchange._stage` 已有的形状），两次并发写不再共用一个文件；② `try/finally` 里 `unlink(missing_ok=True)`，写失败不留 `.part`（第六轮 #4／L20 的那一半就此关掉）；③ 新增 `_ensure_report_file`：渲染留在锁外（64MB zip 是慢的一半，两个不同 job 没理由排队），「判在不在 + 写 + 记日志」进 `threading.Lock`，**输的一方返回赢家的指纹**——`generated_at` 在 payload 里、不在指纹里，同一指纹的两次渲染字节不同，所以"各写各的"会让先返回的那份 sha256 指向一个已经不存在的文档。用例三条：暂存名互不相同、写失败无残留、两请求对同一指纹给出同一 sha256/size 且落盘文档只有一份。**反向**：四条变异（固定暂存名／不清理／整体去锁／输的一方报自己的数字）全判红 |
| 2 | **严重→建议**（检视者原标"并发假设不完整"） | `datasets.py:815-816` vs `818-829`、`BuiltinCatalog`(198-209) | 第十一批新加的签名失效守卫只覆盖 custom 路径；`builtin_view` 提前返回 `BuiltinCatalog._tasks`（无锁、永不失效）。实测：改 scenario 后 custom 读到 `Renamed/After_Edit`，builtin 仍返回 `Office_Productivity/Email`，而**同一文档里 `task.prompt` 是新文本**——一份报表两半来自两个版本。`describe` 标签、`_slices`／`by_*`、`jobs.py:446` 的 timeout 全取旧索引 | 已修（第十二批）：`BuiltinCatalog` 改成持有**一个** `_index_pair = (signature, summaries)` 属性，`tasks` 每次读先比 `_task_file_signature`。用一个属性而不是两个，是为了让发布成为一次赋值——读者要么看到整对、要么看到上一对，不需要锁也不会读到"新签名配旧索引"。实测成本写进了 docstring：签名一遍 150 个任务 **0.55ms**，重新解析 **163ms**。顺手删掉当时留下的无用 `tasks` setter。用例 `test_a_corpus_edit_reaches_the_view_that_was_already_saved`：烘热索引 → 换上一个计数包装的 `_load_task_summaries` → 两次 describe 断言 `parses == []`（命中缓存）→ 往真语料目录写一个新任务文件 → 第三次 describe 断言只解析一次、新标签出现、且**正文里的 `frontmatter` 与索引里的标签一致**（就是发现里那"两半来自两个版本"）。**这条同时关掉了 L32 的失效半边**，L32 的口径问题由实现回答：索引按目录重建，改名 = 删除 + 新增，消失的 id 按 run 聚合告警一次 |
| 3 | 一般 | `reports.py:470-495` + `datasets.py:507-541` | 正文（bodies）没有缓存，被消除的重复全量工作在这条路上还留着。真实语料 150 任务：`tasks_for_run` = 0.141s／0.138s 每次调用；`task_detail` 渲染 1 个任务解析 **40 个**（`load_task=40`）；3 次 full `job_detail` = **120 次**解析 | **不修** → 并入 **L33**（同一根因：`results()`／`_bodies` 不接受已算好的 rows/bodies）。本轮把这三个数字补进 L33，原来只记了报告面那一遍 |
| 4 | 一般 | `datasets.py:525` | `summary is None or not path.is_file()` 分支不记日志。真实"文件被改坏"会改签名 → 重解析 → 任务**静默消失**：实测 `tasks_for_run` 返回 4/5，`datasets.py` **0 条 WARNING**，full 层该条目无 `labels`／无 `prompt` | 已修（第十二批）：收集 `absent` 后在循环外发**一条** `logger.warning("dataset tasks not on disk")`，带 `dataset_id`／`task_ids`（上限 `MAX_LOGGED_TASK_IDS = 20`，常量带"为什么"注释）／`absent_count`／`task_count`。聚合成一条是因为看板轮询报表路由，每次轮询都会走到这里——这正是检视者第 5 类里点出的"循环内 warning 会被重放"。原有那支 `except ValueError` 的 per-file warning 不动（它一次 run 最多几条，且带 `reason`）。用例 `test_a_task_that_vanished_from_disk_is_reported_once_per_run`：三个任务删掉两个 → 只跑一个 + **一条**记录 + 记录里两个 id 都在。**反向**：静默跳过、每条一行两种变异各判红 |
| 5 | 一般 | `reports.py:485` | `except Exception` 把 sqlite `OperationalError`、`PermissionError` 一起吞成"这个数据集缺了"，转发给被评估方的报表少了标签与切片分母，**无硬信号** | **不修** → **L34**（第七轮已登记，同一处、同一口径：先定"哪些异常算缺口、哪些必须让报告失败"，再收成具体类型）。本轮不重复编号 |
| 6 | 一般 | `reports.py:932-949` `_zip` | 整包进 `BytesIO` 再 `getvalue()`，同一份字节两份内存（实测 32MiB 产物 → zip 32.0MiB，RSS 峰值 **+24MiB**）。默认 `64 上传 × 64MiB`（`config.py:176-177`）× 任务数，无上界。本批前已存在，但在被检的读取路径上 | **不修** → 仍是 **L20／L30**（第六轮 #4／第七轮 #6 同一条：`.part` 与保留策略在 L20，闸与内存上界在 L30）。L20 的 `.part` 半边已随发现 1 的 `finally` 关掉，内存与闸那半边不动 |
| 7 | 一般 | `datasets.py:647-662` | 写侧去重（`dict.fromkeys`）没覆盖 `assign_categories`：`current.remove()` 只删第一个。实测遗留重复行 `["field kit","field kit"]` 调用 remove 后仍是 `['field kit']`——取消归档没生效，`delete_category` 继续拒绝 | 已修（第十二批），并在反向验证里**被追问了一次才修对**：第一版只做"读取时按原样去重 + 删全部同名"，反向脚本的一条变异（去重保留、删第一份）判绿——因为它在那份数据上是**等价变异体**。等价就说明修复有一半是装饰：真正的缺口是去重比的是**原样字符串**、而所有比较用的是**归一化名字**，一行里存着 `"Field Kit"`／`"field  kit"` 时 `remove` 永远够不着。改成读取时归一化（`dict.fromkeys(normalize_category_name(name) for name in ...)`），用例改摆两种拼法，变异体换成 `RAW_DEDUPE_ONLY` → 判红。细节记在 `reverse_checks/README.md` 的"第九轮首跑的两条幸存者" |
| 8 | 一般 | `reports.py:381` | `_render(md/html)` 重算一遍 `_bodies`：实测 **+80 次 `load_task`**；zip 再读一次产物行（**用例 396 把这次重复读直接写进断言**） | **不修** → 并入 **L33**。附带把检视者这句记进 L33：`test_job_detail_reads_the_artifact_rows_once_for_a_whole_job` 现在断言的是**当前形状**（zip 那条路读两次），改 L33 时这条断言必须一起改，不能把它当成对外的承诺 |
| 9 | 建议 | `datasets.py:591-601` | `ensure_category` get→insert 非原子，两个 worker 同名分类会撞 PK 抛 `IntegrityError` → 500。与"为共享状态加锁"的立意不一致 | 已修（第十二批）：不用锁——`dataset_categories.name` 是 `TEXT PRIMARY KEY`，让主键当仲裁者，`except sqlite3.IntegrityError` 后 `logger.info("category created elsewhere")`（带 `category`／`by`）并返回**落盘那一行** + `created: False`。加锁要跨进程才成立，而这里的部署形态是两个 daemon 共用一个 sqlite。用例 `test_the_worker_that_loses_a_category_race_reports_the_row_that_landed`：用一个真的会撞主键的包装器先把行落成别人的（`created_by: "someone-else"`），断言输的一方报的是**赢家的行**而不是自己那份。**反向**：改回直抛 → 判红 |
| 10 | 建议 | `store.py:645-646` | `datasets_with_category` 为一个数字做整表读+解码，正是 622-643 立论要避开的那种调用；`delete_category` 每用一次付一次全表 | **不修** → 新增 **L37**。它已经委托给 `category_dataset_counts()`，改法是把"数一个分类"下沉成一条 `SELECT count(*)`，属 `store` 接口变更，与本批的"关检视发现"混在一起会让 diff 失去焦点 |
| — | 建议（资源泄漏类） | `datasets.py` `delete_dataset` | 删数据集不失效 `_indexes`，靠 FIFO 挤出 | **不修**，理由写清：条目上限 32，被删数据集的索引条目从此**不可达**（要读它得先有 record），只是占一格到被淘汰为止；为它加一条失效路径，代价是 `DatasetService` 与 `Store` 之间多一条通知边，换来的收益是一格内存 |

### 用例有效性（第②问的逐条结论）

| 用例 | 检视者结论 | 第十二批处理 |
|---|---|---|
| `test_two_workers_reaching_a_full_cache_do_not_evict_the_same_key`(798) | **确实证它声称的东西**：`/tmp/rv_a_lock.py` 把锁换成空上下文 → `[('KeyError', "'ds_0'")]`，带锁 → `([], 32)`。但同用例的 `assert len(...) == MAX_INDEX_CACHE` **两种实现下都是 32**，真正起作用的只有 `assert not failures` | 已收紧：改成断言 `service._indexes` 的**幸存键集合**——恰好一次淘汰（`len == MAX_INDEX_CACHE`）且两个新键都在。无锁版本会淘汰两次，这条断言才与 `not failures` 各自独立成立 |
| `test_category_counts_read_the_catalogue_once_not_once_per_category`(695) | 断言可靠：spy 匹配 `FROM datasets`，旧实现读 4 次、新实现 1 次 | 无需处理 |
| `test_an_unparseable_task_file_costs_its_task_and_not_the_run`(883) | 属于**"看着证 A 实为 B"**：它用 monkeypatch 在签名不变时抛 `ValueError`，验的是另一支；发现 4 那条真实路径（文件坏 → 签名变 → 重解析 → 静默消失）它碰不到 | 已处理两半：docstring 改写，明说它钉的是"索引说有、读的时候坏"这一支，并交叉引用新用例；真实那支由 `test_a_task_that_vanished_from_disk_is_reported_once_per_run` 覆盖 |
| #1（并发渲染）、#2（builtin 索引过期） | **没有任何用例覆盖** | 已补 4 条（3 条报表 + 1 条语料编辑），见发现 1／2 |

### 复检与反向验证

- `/tmp/reverse_round9.py` 十一条变异：BASELINE **7 passed** → 首跑 **9/11 判红、2 条幸存者**，补齐后 **11/11 判红、零幸存者**，`finally` 恢复后逐文件 sha256 一致。两条幸存者一条是"用例把顺序交给了调度器"（发现 1 的锁）、一条是"变异体与修复等价"（发现 7 的去重），**两条都指向真问题但性质不同**，成因与补齐办法记在 `pal_sdd/feat_acp_remote_eval/reverse_checks/README.md`，脚本已按字节一致归档
- 锚点维护如实记录：第十二批改写了 `tasks_for_run` 的函数体，`/tmp/reverse_round7.py` 的 `SUBSET_READ` 报 `SKIP`（= 计入幸存者），改成整段函数体锚点后重跑 → **7/7 判红**。`reverse_round6.py`（8/8）、`reverse_round8.py`（5/5）本轮各重跑一遍，**锚点未失效、全判红、零幸存者**
- 收口重跑：全量 **570 passed, 1 warning in 19.05s**（563 → 570，+7：报表 3 条、数据集 4 条，另改 2 条既有断言）；H3 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 过滤 `cpd/` 后**仍为空输出**；超宽普查（字符口径，见 §4.13 末段）**仍 49 行／16 文件**，本批新增 0 行；`.py` 文件数 **50**（后端 26／测试 24），本批**未新增文件**
- 严重项结论：**发现 1 与发现 2 均已修**，各带判别性用例 + 反向变异判红；发现 1 的跨进程残余另登记为 L38（不是未修严重项，是那把锁的作用域边界）。满足"严重项未修不许 commit"

### 登记遗留（本轮新增，责任人：anderson）

| # | 位置 | 发现 | 期限／处理 |
|---|---|---|---|
| L37 | `store.py:645-646` `datasets_with_category` | 为一个数字做整表读 + 逐行 JSON 解码，正是 `category_dataset_counts`(628-643) 立论要避开的那种调用；`delete_category` 每用一次付一次全表 | M3 看板接入前（看板会按分类列数据集，这条从"每次删分类付一次"变成"每次刷新付一次"）。改法是把"数一个分类"下沉成 `SELECT count(*) ... WHERE categories LIKE ?` 之外的形式——`categories` 是 JSON 列，真要下沉得先决定是否给分类建关联表，与 J10 的引用保护同批判 |
| L38 | `reports.py` `_report_lock`（发现 1 的第③段） | 这把锁是 `Reports` **实例级**的，`daemon.py:125` 单例构造时它覆盖一个进程内的全部请求；两个 daemon 共用同一个 `exchange_dir` 时，跨进程仍可能各写一次同名报表 | **不预防性加跨进程锁**：当前部署形态是一个 daemon（M2 出口条件），而 `_write` 已经是"唯一暂存名 + 原子 replace"，跨进程最坏结果是两份字节里落盘一份、两个请求各报自己那份的 sha256——不会截断、不会出半份文档。真要跑两个 daemon，先定"报表目录是否允许共享"，与 L20 的保留策略同批 |

## 轮外自查（第九轮等待期间，2026-11-11）：判分代码的执行路径（L39）

- 自查者：本会话。**这不是独立检视**——第九轮 subagent 仍在跑，这一节只登记自查
  发现与已做的修复，不替代第九轮，也不把第九轮的门槛算作已过。
- 范围：`service/grading.py` 新增的锁与包装函数、`tests/cpd/acp_remote_eval/test_grading.py`
  （新建）、核心 `pawbench/grader.py:105-195`（只读，未改一个字节）。
- 材料：源码 + 两份只读探针的实测输出（`reverse_checks/probe_grader_race.py`、
  `probe_grader_nest.py`）。取证过程与数字见 `test_` §4.22。

### 五类必查逐项结论（针对本批新增代码）

| # | 类别 | 结论 |
|---|---|---|
| 1 | 性能 | **有代价，已写进常量注释**：automated／hybrid 的 check script 从最多 4 路并发变成串行。agent 执行并发（`max_concurrent_jobs`）与 judge 的 HTTP 等待都在锁外，用例 3 钉住后者。代价换掉的是"进程状态被改坏 + 打印层数只增不减"，值得 |
| 2 | 未处理异常 | 无发现。`with` 覆盖 raise 路径，用例 2 断言 `not _AUTOMATED_GRADING_LOCK.locked()` 且后续一题仍能判分；`Scorer.score` 既有的 `JudgeFault`／`Exception` 分支未改 |
| 3 | 资源泄漏 | 无发现。锁由 `with` 释放；探针侧 `ThreadPoolExecutor` 用 `with`、子进程由 `subprocess.run` 回收；用例的观测模块在 teardown 从 `sys.modules` 摘掉 |
| 4 | 阻塞卡顿 | **新增一处风险，登记不修**：check script 挂死会占住锁，挡住后续所有判分。今天它已经会挂死一个 job（`to_thread` 无超时，取消 asyncio task 不杀线程），锁把影响面从一个 job 扩到全部判分。不在这把锁上加超时——`threading.Lock` 没有能杀掉线程的超时语义，加了只是把挂死换成误判。真正的解法是 M4 沙箱 + 判分超时（遗留 5） |
| 5 | 日志 | **核心侧有发现，本批不修**：`grader.py:160-166` 的 wrapper print 无 task_id、无级别、cmd／stdout／stderr 全量输出，违反 logging-quality 第 2／3／5 条；并发时无法归属到某次 attempt。CPD 侧本批未新增任何 print 或 logger 调用 |

### 发现与处理

| # | 严重度 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| L39 | 严重 | `pawbench/grader.py:153-181`（核心，只读）＋ `service/grading.py:266`（调用点） | 进程级 `sys.modules["subprocess"]` 补丁在并发判分下互相覆盖：先结束的那条把模块恢复成"它看到的"——可能是另一条的 wrapper。实测两次运行分别 `intact 2/5` 与 `0/5`（结果取决于调度），坏掉的那次 5/5 把 wrapper 永久留在进程里，随后一次无关的 `subprocess.run` 也被打印；连做 3 轮重叠后一次 `echo` 打出 3 份 wrapper 块（层数只增不减）。另：`grade()` 体内 `import subprocess` 的脚本，其 cmd／stdout／stderr 会原样进服务 stdout（顶层 import 不会，因为 `exec` 在换模块之前） | **前半段已修**：CPD 侧 `_AUTOMATED_GRADING_LOCK` + `_grade_automated_exclusively`，窗口不再重叠，核心零改动（H3 仍成立）。**后半段未修**：`exec` 仍在服务进程内、单题判分仍全量打印脚本子进程输出——改这两条要么动核心（第 4 路审批）要么加沙箱，并入遗留 5 |

### 复检与反向验证

- 全量：`575 passed, 1 warning in 18.27s`（572→575，新增 3 条全绿）。
- 用例有效性：`reverse_checks/unlock_plugin.py` 在**内存里**把包装函数换回裸
  `_grade_automated`（源码零写入，因为第九轮正在读文件，不能跑改源码的 `reverse_*.py`）
  → `1 failed, 2 passed`，红的是 `assert 2 == 1`（peak）；去掉插件 → `3 passed`。
  这条变异确定性成立，不像探针那样依赖线程调度。
- H3：`git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml
  requirements.txt | grep -v "/cpd/"` 为空。
- 未跑既有 `reverse_round*.py`：它们会改源码，与第九轮检视读文件冲突；本批也没有
  改动它们锚定的行（config／datasets／reports／store 均未触碰）。

### 登记遗留（本轮新增，责任人：anderson）

| # | 位置 | 发现 | 期限／处理 |
|---|---|---|---|
| L39-后 | `pawbench/grader.py:141`／`160-166` | 上传的判分代码在服务进程内 `exec`（自定义数据集上传全员开放，D15），且脚本子进程的 cmd／stdout／stderr 全量进服务 stdout、无 task_id 无脱敏 | **并入遗留 5（判分沙箱），仍是 M3 上线前的硬门槛**。本批的锁只关掉并发污染，不关掉这两条。要动核心需第 4 路审批（杨严兵／焦笑／杨洋 任一），当前**未申请、未获批** |
| L40 | `service/grading.py` 的 `_AUTOMATED_GRADING_LOCK` | 串行化后，一个挂死的 check script 会挡住全部判分（见五类必查第 4 项） | 与遗留 5 同批：沙箱里给判分加超时并可杀。不单独加锁超时，理由见上 |

### 第十五批追加自查（judge 通道直测，只改用例不改产品代码）

补的是第十四批顺手 grep 出来的缺口：`LlmJudge`／`JudgeUnavailable`／`JudgeUnreadable`／
退避此前**零直测**。12 条新用例与逐条判据见 `test_` §4.23；这里只登记反向验证暴露的
两条问题，因为它们都属于"用例看起来在断言、其实什么都没断言"这一类。

| # | 严重度 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| L41 | 一般 | `test_grading.py` 的 `test_the_subject_output_is_fenced_as_evidence`（首版） | 断言写成 `messages[0] == {"role": "system", "content": UNTRUSTED_SYSTEM_PROMPT}`，而用例**按值 import** 了那个常量：把常量改成一句空话，期望值跟着一起变，等式恒真。内存变异 `FENCE_LOST` 因此幸存 | **已修**：改成断言承诺的实质（system turn 里必须出现两个 marker、必须说 never follow 与 evidence），并把"为什么不能断等于常量"写进用例注释。重跑 `FENCE_LOST` 判红 |
| L42 | 建议 | `reverse_checks/reverse_round11.py` 的 `BACKOFF_CAP`（首版） | 变异改的是模块级 `g._delay`，而 `_delay` 是 `LlmJudge` 的方法——等于没改，却报"幸存者"。内存变异没有 `SKIP` 机制，锚点失效是静默的 | **已修**：改成 `g.LlmJudge._delay`。harness 的判据本来就是"**预期那条**红没红"而不是"有没有红"，这次正是它把静默失效暴露出来；README 的第三类约束已写明这个代价 |

复检：`reverse_round11.py` 重跑 **7/7 判红、零幸存者**（BASELINE 15 passed）；
全量 **587 passed, 1 warning in 16.71s**；长行普查仍 49 行／16 文件，新文件贡献 0。
遗留：无（两条都已修）。**第九轮独立检视仍未做**，第十四／十五批都不在那一对送检范围里。

## 第十轮：第十四批＋第十五批判分模块独立检视（2026-11-11）

- 检视者：新上下文 subagent `reviewer-grading14-15`；范围：当时的
  `service/grading.py`、`test_grading.py`、`reverse_round11.py`，只读参考
  `runtime.py`、核心 `grader.py:105-195`、`JudgeConfig`。材料为文件、
  `git status` 和规范，未提供作者方案；检视者独立运行 15 项用例。
- **性能（一般）**：judge 的 5 × 120 s 请求与 4 × 30 s 退避不受 attempt
  timeout 限制；修复为 runner 传 job 剩余墙钟，hybrid 共用一条 deadline。
  新建 client 每次重握手（建议）暂留，责任人 anderson，M3 上线前评估
  daemon 注入共享 client 的生命周期。
- **未处理异常（建议）**：`_normalize_breakdown` 静默丢弃无数字的 rubric
  条目；可到达该函数的 `criteria_scores` 路径已改为单条聚合 warning 并加用例。
  `scores` 路径的非数字条目在核心 `grader.py:658-662` 更早被静默丢弃，
  CPD 这条告警覆盖不到；责任人 anderson，沙箱接入时决定是否在进入核心
  归一化前记录丢弃数，不把这一半标作已修。
- **资源泄漏（无独立发现）**：正常路径的 client、锁、临时文件都能释放；
  已启动线程无法被取消并非正常释放路径，见下项。
- **阻塞卡顿（严重 1／一般 2）**：原锁无超时且占默认线程池，挂死脚本
  可耗尽 store／lease 使用的 worker；已改独立单 worker 池并按 job 剩余
  时间取消排队请求。**未修严重余项**：正在执行的 check script 无法杀掉，
  停止 job 后仍可操作 workspace，进程退出也可能等待它；归遗留 5 的可杀
  沙箱，M3 上线前硬门槛，不据此宣称 commit 门槛已过。prompt 全量汇总移
  到 `to_thread`；主线程持锁的测试改为用 worker + Event 占用，避免失败时
  `asyncio.run` 等待 default executor 长达数分钟。
- **日志（一般 2）**：judge 重试 warning 加 `task_id`；key 卫生测试补检
  `caplog.records` 的 extra，防止只看 `caplog.text` 而漏判。
- **顺带检视（一般 1／建议 3）**：内存变异脚本补锚点预检、pytest 错误／
  超时分类、保留 PYTHONPATH；断退避 30 s 改为字面量。NO_LOCK 变异和
  hybrid 合分独立变异仍待补，责任人 anderson，下一次判分沙箱检视前。

复检边界：修复后的 23 条判分用例及全量 615 项通过，round11 内存变异
7/7 判红；以上是作者自测，不冒充第二次独立检视。第十轮结论针对旧版
锁实现，当前 pool/deadline 与 redaction 变更须另起新上下文复检。

### 第九轮的状态（如实登记）

第十二批＋第十三批那一对的第九轮检视，先前送检过一次（`reviewer-pair12-13`），
该次**失败返回**（"The request could not be completed"）；重发的
`reviewer-pair12-13b` 至今**未收到完成通知，状态未知**。因此：

- 第九轮**不能算已做**，也不能算"零发现"。
- 第十四／十五批没有等它，而是另起第十轮单独送检（范围不重叠，避免重复劳动）。
- 若 `reviewer-pair12-13b` 之后返回结论，按第九轮回填；若确认已死，重发一次。
  **两种情况都要在 commit 之前有结论**，这是规则的硬门槛，不是可以默认跳过的步骤。

## 第十一轮：撤掉 `shared` 档，只留一个视图（2026-11-23）

- 检视者：独立 subagent（`reviewer-tier-removal`）　检视时间：2026-11-23 11:05
- 检视范围：工作区未提交 diff，1979 行；18 个改动文件（生成产物 `ui/index.js` 与无关的
  `local_eval_report.md` 已排除在送检范围外）
- 提供的材料：diff、18 个改动文件路径、4 份规范（另外三份规则文件）；**未提供作者方案说明**

| # | 严重度 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| 1 | 一般 | `tests/.../test_reports.py:484`、`tools/scan_shared_leakage.py:166` | `md`／`html` 落盘报告被按 `internal` 扫描，而 heading／label／tag 三组形态正则只在 `forwardable` 下跑。改前这两种格式在 `shared` 档是按 `forwardable` 扫过的——正好是"会被贴进 issue、被转发"的两种 | 已修：`md`／`html` 改回 `forwardable`，`json`（带 rubric excerpt）保持 `internal`；同时把 rubric 用例对 md 的断言从「`polite` 不在」扩成同一份词表的 `find_in_text(md, FORWARDABLE) == []`，两个断言并存 |
| 2 | 建议 | `service/reports.py:640-643` | 四个判分侧字段改为无条件 `row[...]`，而同函数的 `trace_id`／`session_id` 用 `_optional()`，怀疑旧库行会 `KeyError` 把轮询详情打成 500 | 不改：`store.py` 的 `CREATE TABLE` 与 reconcile 列清单都含这四列（113/125-128/204-216），打开库即补齐，`_optional` 是为更早的发行版本留的余量。四个字段与相邻十余个字段读法一致，只对这四个做例外反而是不一致 |
| 3 | 建议 | `reverse_checks/probe_round7.py:160,163` | 探针仍以 `sensitivity=`／第二位置参数调 `report()`、`job_detail()`，一跑就 `TypeError` | 已修：改成新签名（探针本身数的是"渲染一次读了几次库"，与档位无关） |
| 4 | 建议 | `reverse_checks/reverse_round9.py:45-67` | 三个变异片段内嵌旧日志行（含 `sensitivity` 字段），改动后 needle 找不到 → 被记成 survivor，产出假的存活清单 | 遗留：该变异体（"日志行里去掉 sensitivity"）随档位一起失效，改 needle 等于改写那一轮的记录。责任人 anderson，下次重跑反向验证前按当前日志行重写 |
| 5 | 建议 | `api.ts:114`、`report.tsx:601`、`test_reports.py:19,1502`、`service/api.py:786` | 注释仍写 "Full tier only"／"full tier"／"shared tier"；`job_detail` 的 docstring 说文档含 timeline，实际时间线在 `task_detail` 里分页给 | 已修：五处措辞按现在的单视图改写；`job_detail` 的 docstring 明确"时间线是第二个请求" |
| 6 | 建议 | `service/reports.py:379-391`、`1212` | zip 渲染在锁外进行，同一指纹的并发请求各建一份最大 64 MB 的 `BytesIO`；落盘后的 sha256 又在全局锁内算。撤掉档位后 zip 人人可点，放大倍数上升 | 遗留：既有实现（本轮未改这段），单用户看板 + 导出面板一次只发一个请求，实测无并发形态。责任人 anderson，M3 前若做并发压测，按指纹加 single-flight 再改 |

复检：第 1 项修复后 `test_reports.py` 58 项通过（`md`／`html` 在更严的 `forwardable` 下零发现，
说明加严没有把正常渲染判成泄露）；第 3、5 项为文案与调用签名，`tsc --noEmit` 干净、全量
`tests/cpd` **672 passed**（本轮 `reverse_checks/` 不在 CI 内）。第 2 项按"不改"结论登记，
理由见上表，未做代码变更。

遗留：上表第 4、6 项；另有第七轮遗留的第九轮检视状态未回填，与本轮无关。

## 第十二轮：console 门（第 21 轮检视）的 20 条发现与处理（2026-11-23）

- 检视者：新上下文 subagent（`reviewer-console-lane`），检视时间 2026-11-23 03:20 UTC
- 检视范围：`pawbench/cpd/acp_remote_eval/console_agent.py`（新增 640 行）、
  `bridge.py` 的 `--console` 那一段（`_App`/`_Proxy._call`/`create_console_app`/CLI）、
  `tests/cpd/acp_remote_eval/test_console_agent.py`（当时 6 项）、
  `manual_acp_remote_eval.md` §3.3 与 §7.3 的改动
- 提供的材料：改动文件全文 + 首次真实作业的证据（`job-c7240d10d5b12140`，
  `session_id=1795404629278-g5uh8wf`，`chats.json` 一行 + 历史文件 +
  `GET /api/chats/{id}` 的 18 条消息）+ 只读的 `QwenPaw/src/qwenpaw/app/routers/console.py`
  与 `app/chats/*`；**未提供作者方案说明**，也未告知新用例断言什么
- 检视者独立做了什么：自己读 `console.py` 的 `post_console_chat_stop` 与 SSE 生成器，
  按五类必查逐项过文件，并按"一轮能怎么结束而没有答案"列出四种形态；未跑用例（当时
  6 项都在作者手里跑过），**仓库零改动**

结论：1 条严重、8 条一般、11 条建议。检视者原话「#4 是唯一一处会让评测结论本身失真的
静默路径，建议优先处理」。按规则"严重项未修不许 commit"，#4 与其余 19 条一并处理如下。

### 五类必查逐项结论

| # | 类别 | 结论 |
|---|---|---|
| 1 | 性能 | #1（连接池上限未声明，池满 30s 排队后报 `console_unreachable`）、#2（每个 attempt 一次全量 `GET /api/chats`）、#3（改名在 `PromptResponse` 前同步 await）、#12（整轮无 idle 边界） |
| 2 | 未处理异常 | #4（四种"没成"都记成 `end_turn` 空答案）、#5（畸形 `data` 块中止整轮）、#6（`session_update` 写失败不处理）、#8（`failed` 映射成 `end_turn`）、#13（stop 不查状态码）、#14（`_chat_id` 失败只打 debug） |
| 3 | 资源泄漏 | #7（`close()` 后静默新建客户端）、#9（`_sessions` 只增不减、`connection` 引用已关闭的 ASGI 对象）、#10（自建 `AsyncClient` 没挂 shutdown） |
| 4 | 阻塞卡顿 | #11（取消路径无超时）、#12（同上）；另有并发节的"同一 session 两条连接互抢 / `running` 是个布尔量" |
| 5 | 日志 | #13/#14（stop 日志说谎）、#15（畸形 SSE 打了 120 字符内容）、#16（一轮起止无 info） |
| — | 越界改动 | 无：改动全在 `pawbench/cpd/acp_remote_eval/` 与 `tests/cpd/`；核心 `pawbench/` 一个字节未动（H3 仍空） |

### 发现与处理

| # | 严重度 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| 4 | **严重** | `console_agent.py` `_stream_turn`/`_apply` | 四种"这一轮没成"的形态都返回 `("end_turn", None)`：200 但非 SSE、流里 `data: {"error": ...}`（`console.py` 的 `event_generator` 就是这么报错的）、`response.status == failed`、流关掉却零事件。评测照常打分，报告里看不出这次是失败 | **已修**，四条各有一个入口：`_require_event_stream` 查 `content-type`；`payload["error"]` 直接 `raise ConsoleError("console_stream_error")`；`status == "failed"` → `console_run_failed`；整轮 `updates == 0`（`cancelled` 除外）→ `console_empty_turn`。四者都是 `ConsoleError`，经 ACP 层变成 `RequestError`，harness 记 `acp_agent_error` |
| 1 | 一般 | 同上 `client` 属性 | 共享 `AsyncClient` 用 httpx 默认池（100/20），代码里没有闸门：并行 attempt 一多先排 30s 再抛 `PoolTimeout`，被归成"console 挂了" | **部分修**：显式 `httpx.Limits(max_connections=32, max_keepalive=16)`，并把 `httpx.PoolTimeout` 单独映射成 `console_capacity`（"桥的容量不足"，不是"console 不可达"）。**不加 `Semaphore`**，理由见 L43 |
| 2 | 一般 | `_stop`/`_chat_id` | 每个 attempt 至少一次全量 `GET /api/chats`（无分页），取消时再一次；这次查询还在 prompt 关键路径上 | **已修**：停止直接用 session id（`post_console_chat_stop` 自己会 `get_chat_id_by_session`，`console.py:601-607`），取消路径**零**列表查询；列表只剩改名那一次，且带 4s 超时。真实作业实测：每轮 1 次 `GET /api/chats`（改名前），取消时 0 次 |
| 3 | 建议 | `prompt` 末尾 | 改名在 `PromptResponse` 返回前同步 await（`list` + `put` 两次请求，read timeout `None`），console 慢时会把一次成功作答拖成 harness 的超时 | **已修**：改名两次请求都 `asyncio.wait_for(..., 4s)`，失败只 warning——名字是便利，对话才是交付物 |
| 5 | 一般 | `_apply` 映射 | 构造 `ToolCallStart`/`ToolCallProgress` 的异常刻意不捕获，一条畸形工具数据会中止整轮、丢掉其后所有内容，还会被记成"被测 agent 出错" | **已修**：`_apply` 包一层，`KeyError/TypeError/ValueError/AttributeError` → warning + `turn.skipped += 1` + 跳过该事件；`_parse_arguments` 保证返回 Mapping（JSON 数组/标量包成 `{"arguments": …}`），因为 ACP 的 `raw_input` 是对象 |
| 6 | 一般 | `_emit` | `connection.session_update` 写失败不处理：客户端已断开时抛个非 `CancelledError` 就打死整轮，而 `prompt` 只对 `CancelledError` 调 `_stop`——运行没人停 | **已修**：捕获写失败 → 清 owner → `_stop` → `raise ConsoleError("console_client_gone")`。"没人读的一轮"不该算成功 |
| 7 | 建议 | `close()` | 置 `_client = None` 但不动注入的客户端，之后再访问 `client` 会静默新建一个真实 httpx 客户端 | **已修**：`_closed` 标志 + 只关自建实例；关闭后再取 `client` 抛 `console_closed` |
| 8 | 建议 | `response.status` | `failed` 映射成 `end_turn`，与正常完成在 `stop_reason` 上完全一样 | **已修**：`failed` → `console_run_failed`（见 #4） |
| 9 | 一般 | `_sessions` | 只在 `close_session` 里删；本仓库客户端 `AcpSession.close()` 只发 cancel 从不发 `session/close`，于是每个 attempt 永久留一个 `_Session`，`connection` 引用着已关闭的 ASGI 对象 | **已修**：一轮结束 `_release()` 清 `connection`（保留轻量的 chat_id）；`closing` 时顺手弹出。配套改了 `bridge._Proxy._call`：**每个 `prompt` 重新把 session 归属到发起它的连接**，否则释放之后下一轮的事件没人收（`test_a_second_turn_on_one_session_still_reaches_its_client` 钉这条） |
| 10 | 建议 | `bridge.py` | 自建 `AsyncClient`/子进程没挂 shutdown，`main` 退出只留下未关闭的连接池 | **已修**：`_close_with_the_server` 把 `backend.close()` 组合在 `create_asgi_app` 已有的 lifespan 外层（Starlette 只跑一个 lifespan，所以是包一层而不是注册第二个） |
| 11 | 一般 | `_stop` | 读超时 `None`，取消时先在 `_stop` 里 await 全量列表再发 stop，全程无界；harness 的 5s 一到先放弃，桥里那个任务还挂着 | **已修，而且真跑才暴露出比原报告更硬的一条**：不止要超时——**stop 本身会被取消连带取消**。真实作业的桥日志里只剩 `httpcore.connection: connect_tcp.failed exception=CancelledError()`，然后什么也没发生，而 console 那边还在写。改成"独立任务 + `asyncio.shield`"，并把它放进 `_stopping` 字典持有引用。修后同一路径实测：`POST /api/console/chat/stop?chat_id=<session_id>` → 200 → `console run stopped` |
| 12 | 一般 | `_stream_turn` | 整轮没有任何 idle/deadline，唯一的边界在 harness 的 `wait_for`；桥分不清"慢"和"死" | **已修**：`_read_events` 用 `asyncio.wait_for(anext(events), idle_timeout)`，默认 **300s**（不是检视者举例的 120s：真实一轮里思考与工具调用之间的最长间隙没超过几十秒，但不想因为一次慢工具把 120s 用成门槛），超时抛 `console_stalled`；构造参数可调，用例用 0.2s |
| 13 | 一般 | `_stop` 日志 | 不查状态码、不看 `{"stopped": false}`，一律 `info "console run stopped"` | **已修**：`raise_for_status()`，读 `stopped`；true → info，false/4xx → warning，各带 session id（用例 `test_a_stop_the_console_did_not_perform_is_logged_as_such`） |
| 14 | 一般 | `_chat_id` | 失败只打 `debug`，而它失败就等于"取消不会发生" | **已修**：warning + session_id + 异常；顺带把该路径从取消路径上摘掉（见 #2），现在它只服务改名 |
| 15 | 建议 | `_decode` | 跳过畸形 SSE 时打了 payload 前 120 字符——那是对话内容 | **已修**：只记 `bytes=<len>`；`_apply` 的跳过日志也只记 `object`/`type`/异常类型 |
| 16 | 建议 | `prompt` 末尾 | 一轮开始/结束没有 info，report 里 transcript 为空时对不上是哪次 attempt | **已修**，且**踩了一次坑**：第一版只写 `extra={...}`，而桥的 logging 格式是 `%(message)s`，实测那行只打出 `console turn finished`，一个数字都没有。改成把 `session=/stop_reason=/updates=/skipped=/tokens=` 写进消息本体（`extra` 保留给结构化消费方）。`reverse_round12` 的 `SUMMARY_HIDDEN` 钉这条 |
| 17 | 一般 | 文本去重 | 去重键是 payload 的 `msg_id` 字符串，而收尾的全文行 `msg_id` 是 `null` → 键变成 `""`，同一段话被发两次（测试夹具正是这个形状） | **已修**：`_Turn.resolve_message()` —— 空 `msg_id` 沿用"当前 message"，`streamed` 按 message 记。真实作业实测：我们收到的 726 字符与 console 存下的 858 字符做 `difflib` 对齐，**只有 console 侧的两处 insert**（首句 57 + QwenPaw 自己追加的 `⟦ … ⟧` 收尾注解 132），零 delete/replace——即没有重复也没有丢 |
| 18 | 建议 | reasoning 判定 | 依赖 `msg_id` 命中 `message_types`；最终行 `msg_id` 为 null 或 `message` 事件晚于首个 content 时，思考被当成正文 | **已修**（同一处 `resolve_message`）。**留下的限制**：`message` 事件晚于首个 content 到达时，那几块已经按"正文"发出去了，事后无法回收——真机没出现过，写进 `_Turn` 的 docstring 而不是假装解决 |
| 19 | 建议 | 非 text/data 块 | `refusal` 被压成 `[refusal]` 标记，语义丢失 | **已修**：`refusal` 走正文（有 `text` 就用它的字，没有才 `[refusal]`）。图片/文件/音频仍是 `[<type>]` 占位 + `debug` 里带 msg id——**不改**：transcript 会被 judge 读，往里塞内部 msg id 是拿可读性换一个没人会用的线索 |
| 20 | 建议 | `_tool` | 完成态工具行必须同时满足"非 delta + `status == completed`"：少一个字段、字段顺序不同、完成行回显 arguments，工具调用就静默消失 | **已修**：以 `call_id` 为单位做 upsert——见 `name` 就发 start（只在 `arguments` 非空 / 无 output / 非 delta 时才发，免得公告一次空参数）、见 `output` 就发 progress，`delta`/`status` 都不再是存在条件（`test_a_tool_call_survives_a_console_that_omits_delta_and_status`） |
| — | 并发节 | `route`/`running`/`close_session` | 同一 session 两条连接会互抢归属且只在 debug 里留一句；`running` 是布尔量，第二个 `prompt` 的失败路径会把第一个的运行状态抹掉；`close_session` 会在跑的时候把 state `pop` 掉，之后每次 `_emit` 都查不到 owner | **已修**：`route` 换主时 warning；`prompt` 发现 `running` 直接 `console_session_busy`（console 那边是 409，这里说清是自己）；`close_session` 在跑时置 `closing` 交给该轮的 `finally` 回收 |

### 用例有效性（本轮 +17，6 → 23）

| 用例 | 钉的是什么 | 对应发现 |
|---|---|---|
| `test_a_turn_that_says_nothing_is_a_failed_attempt` | 零事件的 `completed` 不是成功 | #4 |
| `test_a_stream_error_is_a_failed_attempt_not_an_empty_answer` | `data: {"error": …}` | #4 |
| `test_a_200_that_is_not_an_event_stream_is_a_failed_attempt` | 200 + `application/json` | #4 |
| `test_a_failed_run_is_not_reported_as_a_finished_turn` | `status: failed` | #8 |
| `test_the_answer_is_sent_once_even_when_the_closing_row_names_no_message` | 同一段话只发一次 | #17 |
| `test_a_tool_call_survives_a_console_that_omits_delta_and_status` | 少字段不吃掉工具调用 | #20 |
| `test_a_refusal_reaches_the_transcript_as_the_words_it_was` | 拒答的字要留下 | #19 |
| `test_a_second_turn_on_one_session_still_reaches_its_client` | 释放连接后下一轮还能收到事件（bridge 重归属） | #9 |
| `test_a_finished_turn_lets_go_of_the_client_connection` | 一轮结束就放掉连接 | #9 |
| `test_a_cancelled_turn_stops_the_console_run` | 取消按 session id 发、且不查列表 | #2 |
| `test_a_client_that_stops_reading_stops_the_console_run` | 写失败要停运行并失败该轮 | #6 |
| `test_a_stop_the_console_did_not_perform_is_logged_as_such` | `stopped: false` 不说谎 | #13 |
| `test_a_console_that_goes_quiet_fails_the_turn_instead_of_hanging` | idle 超时 | #12 |
| `test_a_cancel_that_loses_its_client_still_stops_the_console_run` | shield：客户端走了 stop 也要发出去 | #11 |
| `test_two_callers_asking_to_stop_share_one_request` | 一次取消只发一次 stop | 真机跟进 |
| `test_the_turn_summary_is_readable_in_a_plain_log_line` | 摘要数字在消息里，不在 `extra` | #16 |
| `test_a_closed_agent_does_not_open_another_connection` | 关闭后不偷偷新建客户端 | #7 |
| `test_a_busy_session_is_told_so_instead_of_racing_itself` | 同 session 并发 prompt | 并发节 |

### 反向验证

`reverse_checks/reverse_round12.py`：**15 条变异，15/15 判红、零幸存者**，`finally` 恢复后
逐文件 sha256 与运行前一致（`restored console_agent.py: ok` / `restored bridge.py: ok`）。
BASELINE 23 passed。

这一轮**刻意选了改源码而不是内存变异**：15 条里有 9 条是"删掉一个守卫""改一个去重键"，
用属性重绑要么做不到、要么得把整个方法抄一遍（抄一遍就是在测抄的那份）。代价是运行期间
源码被改，所以脚本头部写明了"不要与独立检视并行跑"。

按 README 的第三类约束记两条锚点失效（都没有被当成判红糊过去）：

1. **`STOP_VIA_LIST`**：`_stop` 拆成 `_stop` + `_request_stop` 之后原锚点（`if not session_id:
   return` 紧跟 `import httpx`）为 0 命中 → 脚本报 `SKIP` 并计入幸存者，按新结构改到
   `_request_stop` 头部后判红。
2. **`NO_SHIELD`**：`await asyncio.shield(task)` 因 stop 去重改名成 `pending` 而失效 → `SKIP`
   → 改锚点后判红。这正是 README 说的"内存/文本变异没有类型系统兜底，锚点失效是静默的"。

### 真实端到端（不是用例）

三条真实作业，全部走服务（`http://127.0.0.1:8471`）→ 桥（`--console http://127.0.0.1:8088
--agent pawbench_eval --port 8474`）→ 真 console：

| 作业 | 结果 | 观测到的东西 |
|---|---|---|
| `job-b228b5e26a88ee03`（修 #4/#17 前一轮的代码，作为对照） | finished，`overall 1.0`，`session_id=1795405812343-9hwkro2` | `chats.json` 一行、名字 `T097_pinbench_eli5_model_summary · job-b228b5e26a88ee03（第 1 次）`、历史文件 `default_<sid>.json`；transcript 38 事件、`damaged_events: 0`、工具调用带 `args` 与结果 |
| `job-8e4188770f0b33e7`（最终代码） | finished | 日志：`console turn finished: session=1795406767628-ttlezt6 stop_reason=end_turn updates=234 skipped=0 tokens=86285`；每轮只有 1 次 `GET /api/chats`（改名前），取消时 0 次 |
| `job-e62c0e23c9731ba8` / `job-f29eeff1746dba3d` / `job-098a5d91c37ebb27`（取消路径） | canceled | 前两次暴露"stop 被连带取消"（`connect_tcp.failed CancelledError`）与"一次取消发两次 stop"；最后一次是修完的形状：**一次** `POST /console/chat/stop?chat_id=<session_id>` → 200 → `console run stopped` |

另外核对了两件报告里读不出来的事：① 我们的 transcript 与 console 存下的文本做 `difflib`
比对，差异只有 console 侧两处 insert（见 #17），说明"不发两次"没有靠丢字换来；②
`GET /v1/jobs/{id}/transcript` 的 `transcript_state: ok`、`damaged_events: 0`。

测试期间在 `pawbench_eval` 的会话列表里产生的 6 个临时会话（取消/复现用）已用
`POST /api/chats/batch-delete` 清掉，留下 3 个真实作业的会话（按 `task · job（第 n 次）`
命名）供人工核对。

### 复检

- `tests/cpd` 全量 **695 passed**（678 → 695，本轮 +17；`bridge.py` 的路由改动没有影响
  stdio 门的三条既有用例——第一次跑时 `AttributeError: 'ClientSideConnection' object has no
  attribute 'route'` 就是它抓到的：路由必须发给**桥的后端**，不是被解析出来的子进程）
- `py_compile` 通过（该 venv 无 ruff）
- 反向验证 15/15 判红、零幸存者，恢复后 sha256 一致
- H3：`git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml
  requirements.txt` 过滤 `cpd/` 后仍为空

### 登记遗留（本轮新增，责任人：anderson）

| # | 位置 | 发现 | 期限／处理 |
|---|---|---|---|
| L43 | `console_agent.py` 的 `client`（`httpx.Limits`） | 池上限声明了、`PoolTimeout` 也单独识别了，但**没有**显式的并发闸门（`Semaphore`）：一次压测把 `max_concurrent_jobs` 调到 20 以上时，超出 32 条连接的 attempt 会等 30s 再收到 `console_capacity` | **不预防性加闸**：服务侧 `queue` 已经是并发闸（默认 4），桥里再加一层会造出第二个上限，而阻塞式等待没有任何反馈。真要跑 32 路以上，先定"桥的容量是多少、超了怎么退避"，与 L30 的上界同批 |
| L44 | `console_agent.py` `_Turn.noted` / `message_types` | 一轮之内按 message 累积，不回收。一轮的消息数由 console 决定，理论上无上界 | 不单独修：`_Turn` 随轮次结束一起回收，单轮上万条 message 的对话不是评测形态。若将来出现长跑 agent，再按"每条 message 只留类型"收窄 |

## 第十三轮：提交表单补上环境指纹（2026-11-23）

- 检视者：新上下文 subagent（`reviewer-fingerprint-form`），只看 `git diff` + 改动文件 +
  四份规范 + 服务端契约（`service/jobs.py` 的 `_checked_fingerprint`、`cli.py` 的 `_env_pairs`），
  **未提供作者方案说明**，未运行 pytest / build，仓库零改动
- 起因（用户原话）：`为啥最新的评测 环境指纹为空了`。查下来不是回归：29 条作业里 6 条有指纹，
  提交人全是 `smoke` / `eval-run`（脚本带 `--env`），其余 23 条全是 `null`，提交人 `aaa` /
  `anderson`（看板与手工 curl）。链路只有两处会写这个字段——CLI 的 `--env`，以及服务端
  收到 `env_fingerprint` 时的原样存——而**看板表单没有这一栏**（`git log -S env_fingerprint
  -- plugins/` 只有两次命中，都是读+展示，没有一次写）
- 结论：0 条严重、1 条一般、若干建议。按建议处理的四条都改了。

### 发现与处理

| # | 严重度 | 位置 | 发现 | 处理 |
|---|---|---|---|---|
| 1 | 一般 | `new-job.tsx` 的 TextArea / Alert | `problems.join("；")` 全量渲染，且输入无上限：粘贴一段 500 行 env 会生成数百条"第 N 行不是 key=value"，弹窗卡顿且错误不可读 | **已修**：`shownProblems()` 只列前三条 + `另有 N 行`；`shownKeys()` 同理（`a、b、c 等 5 项`）。**不加 `maxLength`**：`maxLength` 会让浏览器静默截断粘贴，那正是这一栏要避免的"悄悄丢数据"；解析本身是 O(n)，钉住渲染就够了 |
| 2 | 一般 | 同上 + manual §4.1 | manual 写"服务端既不校验也不补全"不成立：`_checked_fingerprint` 会拒非对象（`env_fingerprint_invalid`）与超 4 KB（`env_fingerprint_too_large`） | **已修**：文档改成"不按语义校验，但形式上拒非对象与超 4 KB"；表单空态 hint 末尾补"服务上限 4 KB"；**不在前端截断**，超限由服务端明确拒绝 |
| 3 | 建议 | `parseFingerprint` | `pairs["__proto__"] = "x"` 对普通对象是空操作：`hasOwnProperty` 假、`Object.keys` 不含，于是这一行既不报错也不发出——**唯一一条会无声消失的路径**，与本栏"不默默丢一行"的承诺直接冲突 | **已修**：`Object.create(null)`。实测 `__proto__=x\nmodel=m` → `Object.keys` 两个都在，`JSON.stringify` 出 `{"__proto__":"x","model":"m"}`，服务端收到两个键 |
| 4 | 建议 | 同上 | 值被 `trim()`，而注释/文档写的是"stored verbatim" / "原样存进报告" | **已修文字不改行为**：粘贴带进来的首尾空格不进报告是想要的，所以把说法改成"去掉首尾空白后存进"，并在 manual 的四条阅读规则里写明"整行先去掉首尾空白" |
| 5 | 建议 | `test_plugin.py` 新用例 | **断言在改动前就为真**：`"env_fingerprint" in UI_BUNDLE` 因为报告面板 `report.tsx` 早就读这个字段，`git show HEAD:index.js` 已含它。所以那条断言根本发现不了"改了表单忘了 rebuild"，而 docstring 声称的主要目的正是这个 | **已修**：改钉提交行本身 `if (fingerprint.count) body.env_fingerprint = fingerprint.pairs;`，源码与产物各断言一次，另断言产物里仍有报告空态的文案。实测把旧产物放回去 → 该用例**判红**（`AssertionError`），恢复后绿 |
| 6 | 建议 | `test_jobs.py` 新用例 | docstring 说 `{}`/`""`/`[]` 都折成 `None`，实际只断言了 `{}` 与缺省 | **已修**：改成四种形状的循环断言，任一种不再折成 `None` 都会红 |
| — | 越界 | `pal_sdd/feat_siliconflow_local_eval/local_eval_report.md` | 工作区里有一份与本功能无关的表格对齐改动 | **未纳入本次提交**（它是另一条特性留下的，不在本批 diff 里），保持原样不碰 |

### 与 CLI 的差异（检视者要求逐条给出判断）

| 维度 | CLI `--env` | 表单 | 判断 |
|---|---|---|---|
| 切分 | 第一个 `=` | 第一个 `=` | 一致 |
| 键 | trim，空键报错 | 同 | 一致 |
| 值 | **原样保留** | 整行 trim 后取 | 有意不同，已写进 manual 与注释：表单是粘贴面，粘来的空格是噪声 |
| 空行 | 参数不允许为空 | 跳过 | 有意不同（末尾换行不是错） |
| 重复键 | 后者覆盖前者 | 报错拦截 | 有意不同：静默覆盖等于对报告说一句没人支持的话 |

### 真实页面验证（不是用例）

用 Playwright 驱动**真 console**（`http://127.0.0.1:8088/apps/pawbench-eval`）+ 已安装副本，
把提交请求用 `route` 拦下来（只拦 POST，GET 放行）并回 400，所以**没有真的排一条作业**：

- 填 `model=gpt-6-sol` + `agent_id=pawbench_eval` → 提交体
  `{"acp_url":…,"product":"QwenPaw 2.2.2","purpose":…,"selector":…,"window":{"kind":"immediate"},"env_fingerprint":{"model":"gpt-6-sol","agent_id":"pawbench_eval"}}`
- 填 `model=…` + `model=qwen3-max` → 弹窗前出现 `第 2 行的 model 与前面重复`，hint 变
  `改好上面那几行才能提交`，提交被拦（截图 `/tmp/new-job-duplicate.png`）
- 填 6 行非法 → `第 2 行…；第 3 行…；第 4 行…；另有 3 行`
- 一次误把列表 GET 也拦了，页面左下角显示"服务不可用"；只拦 POST 后恢复"已连接"——
  顺带证明那个徽标是真的在反映可达性，不是摆设

### 复检

- `tests/cpd` **695 → 697**（`test_plugin.py` 25、`test_jobs.py` 41）
- `tsc --noEmit` 通过；`npm run build` 产物 176 196 B；旧产物回放可判红
- 已装副本同步：`plugins/pawbench-eval/ui/index.js` 与 `~/.qwenpaw/plugins/pawbench-eval/ui/index.js`
  逐字节一致（`qwenpaw plugin install --force` 会 `rmtree` 目标目录，把 `data/config.json`
  一起删掉；这次是先备份、装完再恢复，sha256 与备份一致）

### 登记遗留

| # | 位置 | 发现 | 期限／处理 |
|---|---|---|---|
| L45 | 表单的环境指纹 | 4 KB 上限只由服务端拒绝（400），前端不做字节预估，粘贴超限时要提交一次才知道 | 不修：前端估算只能近似（Python `json.dumps` 的分隔符与 JS `JSON.stringify` 不同），估错会变成"前端说超了、服务端其实收得下"或反之；明确拒绝比猜上限好 |
