# Test：ACP 远端 Agent 评测

> 状态：**M1 已执行，记录见 §4**（数据面、ACP 客户端、队列、调度、数据集、Runner 与假 agent 端到端全绿）。A/B/F/G/K/R 各组仍未执行——它们依赖 M2 之后的判分链路、看板与真实 QwenPaw 通道。
> 说明：规则引用的 `pal_sdd/_templates/test_case_matrix.md` 在本仓库不存在，十维判定按本文件 §1 定义的维度集执行；模板补齐后迁移。

## 1. 十维判定定义

| # | 维度 | 判定问题 |
|---|---|---|
| 1 | 功能正确 | 需求 1–5 各自的主路径是否成立 |
| 2 | 契约一致 | 结果 JSON 与 `submissions/*.json` schema 兼容；transcript 与 `agents/transcript.py` 结构一致 |
| 3 | 边界 | 空评测集、单任务集、超大产物、零产物、超长 prompt |
| 4 | 异常路径 | ACP 连接失败/中途断、远端超时、judge 不可用、上传迟于 deadline |
| 5 | 并发与时序 | 并发上限、调序、取消、同用户重复提交 |
| 6 | 恢复与幂等 | 服务重启后队列状态、重复提交同 job、结果重复写 |
| 7 | 安全 | 白名单外 token、档位参数被当越权来猜（`shared`+`zip` 要回 400 不回 403）、路径穿越、黑名单文件名、题库枚举、SSRF、日志与 URL 泄露 |
| 8 | 性能 | 队列调度开销、SQLite 在 1000 job 下的列表响应、并发 4 时内存 |
| 9 | 回归 | 现有 `run_bench.py` CLI 三条路径（qwenpaw/openclaw/hermes）分数不变 |
| 10 | 可用性 | 插件看板：双主题、调序操作可键盘完成、失败原因可读、无前端 console 残留 |

## 2. 覆盖矩阵

> **结果列的读法**：这一列是**开工前的计划状态**，不是执行结论。M1 已执行到哪、每一项结论如何，以 §4.2 的分用例记录为准（含"通过（部分）"这类只覆盖半个判据的情况——不要把 §4.2 的"通过"当成整行判据达成）。判定列里涉及判分、看板、真实远端的半格，M2 之后才可能变绿。

| ID | 场景 | 维度 | 用例 | 判定 | 证据 | 结果 |
|---|---|---|---|---|---|---|
| A1 | 场景 2 内置集 | 1,2 | 假 ACP agent（fixture 内脚本）提交 3 任务 | 出分且 schema 字段齐 | `results/…/jobs/{id}` + 结果 JSON | 待执行 |
| A2 | 场景 2 内置集 | 4 | ACP 地址不可达 | job=`failed(acp_unreachable)`，非 0 分记录 | 服务日志 + job 详情 | 待执行 |
| A3 | 场景 2 内置集 | 3,4 | 远端跑完但零产物 | `failure_reason: no_artifacts`，计入 `tasks_missing`，不进分母 | job_tasks 行 | 待执行 |
| A4 | 场景 2 内置集 | 2 | 与同环境 harness 对照同任务 | 分数差可解释，两档不混排 | 对照表 + 分数差 | 待执行 |
| A5 | pilot 带附件题 | 1,2,3 | 假 ACP agent 拉 fixture、写产物、PUT 回来（xlsx/png 各 ≥1 题） | 结果里三段证据齐：manifest 下发记录 + artifacts 行 + 本地重建 workspace 参与判分 | job_tasks、artifacts 表 + workspace 目录快照 | 待执行 |
| B1 | 场景 1 自定义集 | 1 | skill 准备的包 → `validate_dataset_package` 通过 | 校验报告全绿后进队列 | validation_report JSON | 待执行 |
| B2 | 场景 1 自定义集 | 3 | 缺 `## Prompt` / 缺 `grading_type` | 拒收并给逐项原因，不进队列 | 400 响应体 | 待执行 |
| B3 | 场景 1 自定义集 | 7 | 包内带 `grade.py` 里 `os.system` 越权尝试 | 沙箱内网络隔离 + 越权失败 | 沙箱日志 + 容器退出码 | 待执行 |
| B4 | 场景 1 自定义集 | 4 | 判分脚本超时/输出不可解析 | `grading_error`，不当 0 分 | job_tasks 行 | 待执行 |
| C1 | 队列 | 5 | 提 6 个 job，`max_concurrent_jobs=4` | 同时 running ≤ 4，其余 queued 且 pos 单调 | 时序快照 | 待执行 |
| C2 | 队列 | 5 | queued 任务调序到中位 | `queue_pos` 取中值生效，出队顺序变 | PATCH 响应 + 出队日志 | 待执行 |
| C3 | 队列 | 5 | running 任务请求调序 | 拒绝（只允许 cancel） | 409 响应 | 待执行 |
| C4 | 队列 | 5 | 同用户连提 2 个（`max_running_per_user=1`） | 第二个 `429` 并返回等待量 | 429 响应体 | 待执行 |
| C5 | 队列 | 6 | kill -9 服务后重启 | 心跳超时的 running → `failed(recovered)`，不自动重跑 | 重启日志 + 状态 | 待执行 |
| C6 | 队列 | 1 | 运行中取消 | 远端收到 `session/cancel`，产物不再接收 | ACP 侧抓包 + job 状态 | 待执行 |
| D1 | 鉴权 | 7 | 白名单外 token 调 5 类端点 | 全部 401，无信息泄露 | 响应体 | 待执行 |
| D2 | 鉴权 | 7 | 过期 / revoked token | 401，日志含 subject 与 hash 前 8 位、无明文 | 服务日志 | 待执行 |
| D3 | 鉴权 | 7 | 白名单内**任一** token 读他人 job 的 `full` 详情、judge 依据与产物下载口 | 全部 200（已定：两档都对白名单内全员开放，不再有 `read_all`） | 响应体 + 下载成功 | 待执行 |
| D4 | 鉴权 | 7 | 白名单外 token 分别访问"存在的 job"与"不存在的 job" | 两者都 401 且响应体形状一致，不能用状态码差异枚举 job_id | 两份响应体 diff | 待执行 |
| E1 | 数据面 | 7 | `PUT ../etc/x` / 绝对路径 / 未声明 output | 全部拒收，workspace 无越界文件 | 目录快照 | 待执行 |
| E2 | 数据面 | 7 | 上传 `conftest.py`、`.pth` | 黑名单拒收，判分进程未采集 | 判分日志 | 待执行 |
| E3 | 数据面 | 7 | run_token 跨 task / 复用 / 超 TTL | 403/410 | 响应码 | 待执行 |
| E4 | 数据面 | 7 | 枚举 task id 拉 asset | 限速 + 只允许本 run 分配的 id | 服务日志计数 | 待执行 |
| E5 | 数据面 | 1,2 | 二进制 fixture 与产物（xlsx/png）往返 | sha256 一致 | manifest 记录 + 校验 | 待执行 |
| E6 | 数据面 | 7 | 请求头伪造 `Host: evil.example` | 响应里的 asset/上传/报告 URL 仍由 `service.public_base_url` 拼出，不受 `Host` 影响 | 三份响应体 | 待执行 |
| E7 | 数据面 | 4 | `public_base_url` 缺失启动；以及它指向对端不可达的 `localhost` | 前者启动即失败并指名配置项，不隐式默认；后者失败诊断区分 `assets_unreachable`（拉取 0 命中）与 `agent_refused`（远端拒执） | 启动日志 + job 详情 failure_reason | 待执行 |
| F1 | 判分 | 7 | 产物内含 judge 指令劫持文本 | 边界包裹生效，judge 不被带偏；抽检留证 | judge prompt + 评分 | 待执行 |
| F2 | 判分 | 2 | manifest 泄露检查 | 响应体不含 `expected_behavior`/rubric/判分码 | 全任务响应 grep | **通过**（`test_exchange.py::test_a_manifest_carries_nothing_from_the_grading_side`，扫的是序列化前的 payload + 一条植入项做反证；见 §4.13） |
| G1 | 插件 | 1,10 | 三人各自提交并互见队列 | 看板显示全部，提交人可辨 | 截图（浅色+深色） | 待执行 |
| G2 | 插件 | 7,10 | token 不出现在前端 storage / URL | DevTools 检查无明文 | 截图 | 待执行 |
| G3 | 插件 | 10 | MCP 未启用时的 skill 门控 | 提示引导，不静默失败 | 截图 + 日志 | 待执行 |
| G4 | 插件 | 1,9 | 从本仓库路径 `qwenpaw plugin validate` + `install`，装完启动 QwenPaw；再在**升级后的 QwenPaw** 上重跑一遍 | 三步全绿：validate 通过、后端模块导入成功、看板页可打开。插件不在 QwenPaw 官方目录里（D20），契约漂移没有对方的兼容性测试兜底，这条是我们自己唯一的哨兵；失败要能指出是 `plugin.json` 字段、SDK 注册 API 还是依赖缺失 | CLI 输出 + 启动日志 + 截图 | 待执行 |
| G5 | 插件 | 6 | 装到 `~/.qwenpaw/plugins/pawbench-eval` 后，把仓库工作目录改名再启动 | 仍正常加载：运行时不解析仓库相对路径，skill 模板与配置从安装目录与工作目录取。另核对改了插件代码后不重新 `install --force` 时看板仍是旧版（`copytree` 不是 symlink，分发节奏必须写进 README） | 启动日志 + `plugin list` 的 Location | 待执行 |
| H1 | 回归 | 9 | 三条 CLI 路径重跑 pilot 任务 | 与改造前分数一致 | diff 报告 | 待执行 |
| H2 | 回归 | 8 | 1000 job 下列表响应 | `GET /v1/jobs?limit=50` P95 < 300ms | 压测输出 | 待执行 |
| H3 | 合并边界 | 9 | 特性分支相对 `main` 做一次全量 diff，按目录归类 | `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 里除 `pawbench/cpd/acp_remote_eval/**`、`tests/cpd/acp_remote_eval/**` 与依赖块那一处外**应为空**；`pawbench/agents/factory.py`、`run_bench.py`、`data/pawbench-v1.0/**` 明确零改动。这条是 design §2.1 边界的唯一机器证据——社区特性后续还要往这个仓库合，边界一旦被写代码的人顺手破掉，就不会再有人补回来 | `git diff --name-only` 原样输出贴进执行记录 | 待执行 |
| I1 | 调度 | 1,5 | 三种窗口各提一个（即时/夜间/自定义） | 即时立刻 running；夜间在模拟 00:00 后起跑；自定义到 `not_before` 起跑 | 冻结时钟下的状态时间线 | 待执行 |
| I2 | 调度 | 5 | 23:40 提"夜间"（不足 30 分钟） | 不当晚起跑，排到下一窗口 | 状态 + 日志 | 待执行 |
| I3 | 调度 | 5 | 06:55 起跑、单任务超时 20 分钟，窗口 07:00 结束 | 默认宽限：在跑任务跑完，不掐 | job_tasks 时序 | 待执行 |
| I4 | 调度 | 5,7 | 窗口内只跑到 60% 题 | 其余记 `skipped(window_closed)`，不进分母、不算 0 分 | 结果 JSON 的 tasks/scores | 待执行 |
| I5 | 调度 | 5 | `hard_stop: true` 时窗口边界 | 远端收到 `session/cancel`，任务记 `window_closed` | ACP 侧记录 | 待执行 |
| I6 | 调度 | 6 | `scheduled` 期间重启服务 | 按当前时钟重算，不会提前起跑；`queue_pos` 保留 | 重启前后状态 diff | 待执行 |
| I7 | 调度 | 1,8 | 时钟跨度到 DST/跨日/跨月边界（自定义区间） | 窗口解析与展示换算一致，无 1 小时漂移 | 各时区快照 | 待执行 |
| I8 | 调度 | 5,10 | 队列同时有即时与 scheduled | scheduled 不占并发位；即时任务不因夜间排队而被阻塞 | tick 日志 | 待执行 |
| J1 | 数据集 | 1 | 建 `builtin_view`（scenario=Office_Productivity） | 解析出 task_ids 快照，数量与 labels 分布一致 | resolve 响应 | 待执行 |
| J2 | 数据集 | 1,3 | 混合选择：2 个单集 + 1 个分类，故意重叠 | 去重后任务数正确，`duplicates_removed` 与 `by_dataset` 可核对 | resolve 响应 + job 详情 | 待执行 |
| J3 | 数据集 | 6 | 提交后再改数据集内容 | 历史 job 仍按 `resolved_task_ids` 快照复现，不漂移 | 重放旧 job 的 task 清单 | 待执行 |
| J4 | 数据集 | 7 | 非 owner 改/删他人数据集；非创建者删他人分类 | 403（建仍全员开放，改/删收紧） | 响应体 | 待执行 |
| J5 | 数据集 | 7 | task md 内嵌 judge 劫持语句 / `conftest.py` 文件名 | 注册阶段拒收 | validation_report | 待执行 |
| J6 | 数据集 | 4 | resolve 里含不存在 task id、空选择器、超 500 题 | 明确报错，不进队列 | 400 响应体 | 待执行 |
| J7 | 数据集 | 1 | 删除被引用的分类 / 被 job 引用的数据集 | 409 并给引用计数 | 响应体 | 待执行 |
| J8 | 数据集 | 9 | skill 的 catalog 工作流走 MCP 全链路 | 与看板走同一 resolve 实现，结果字节一致 | 两侧响应对比 | 待执行 |
| J9 | 数据集 | 1,9 | pilot 种子启动断言（附件题 ≥5、形态 ≥2 类、closed/open 各有、judge/脚本各有） | 断言不满足时服务明确拒绝就绪并把缺口列成清单，不静默起一个"看起来是 15 题"的集 | 启动日志 + 断言单测 | 待执行 |
| J10 | 数据集 | 3,7 | 两个用户用近义名建同一分类（`Office Productivity` / `office_productivity` / 全角空格） | 规范化后命中同一分类，表里不出现第二条；`POST` 幂等返回既有 id | dataset_categories 快照 | 待执行 |
| K1 | 详情 | 1,2 | 看板详情、`GET /detail`、MCP `get_job_detail` 同参数各取一次 | 三份响应除 `sensitivity` 标记外字段集一致（同一聚合函数） | 三份 JSON 字段集 diff | 待执行 |
| K2 | 详情 | 7 | `shared` 档响应做泄露扫描 | 不含 `expected_behavior`、rubric 原文、判分源码、judge 完整 prompt | 关键词 + 正则扫描脚本输出 | **通过**（`test_reports.py::test_the_forwardable_documents_pass_the_leakage_scan`：shared detail / results / full detail 三份 payload ＋ `md`·`html`·`json` 三份**落盘渲染文件**同一套规则扫，另有两条植入项证明扫得出来；见 §4.13） |
| K3 | 详情 | 7 | 非提交人带自己 token 取 `sensitivity=full`，与提交人本人取同一 job 同一档位做对比 | 两者都 200 且**字段集一致**（档位是外发边界、不是人员边界，D21）；服务端不因调用者是谁而静默降级成 shared——静默降级比拒绝更坏，提交人会以为发出去的是完整版 | 两份 JSON 字段集 diff | 待执行 |
| K4 | 报告 | 7 | `shared` 档请求 `format=zip` | `400 sensitivity_format_mismatch` 并说明原因，**不是 403**（没有一条权限可申请）；看板前端不提供该组合，不让用户点出去才发现 | 响应体 + 前端截图 | 待执行 |
| K5 | 报告 | 2,6 | 同一 job 同一 `sensitivity` 四次生成 json/md/html/zip | 内容一致、`sha256` 可复现（无时间戳/随机序污染） | 两次生成对比 + sha256 | 待执行 |
| K6 | 报告 | 6 | job 数据集被改后取旧报告 | `stale_before` 命中，返回过期标记而非旧内容冒充最新 | 响应体 + reports 表 | 待执行 |
| K7 | 详情 | 3,4 | running / queued / failed 三种未完成态取详情 | 已完成题目给分、未完成给进度；不出现空结构或 500 | 三种状态响应样本 | 待执行 |
| K8 | 详情 | 3,8 | 单任务 transcript 10 万行、artifacts 合计 > 1 GiB | 分页不超时（`cursor`/`limit` 生效）；zip 走流式，服务内存峰值不随体积线性涨 | 分页时序 + 压测内存曲线 | 待执行 |
| K9 | 报告 | 7 | 报告下载 URL 二次使用 / 过 TTL | 二次 403、过期 410，URL 不落日志明文 | 响应体 + 日志脱敏检查 | 待执行 |
| K10 | 详情 | 10 | 非提交人在看板打开他人 job，切两次档位 | 默认 `shared` 可读；"完整版"开关**对任何人都在**（不是只给提交人，否则 D21 的开放只存在于 API 层、看板看着仍像无权），切过去时旁边固定一行「完整版含评分依据与他人产物，对外只发 shared 版」；文案不能靠 tooltip，档位切换不能改变列表滚动位置 | 截图（浅色+深色，shared/full 各一张） | 待执行 |
| R1 | 真实服务通道 | 1,2 | 本地 QwenPaw 作被测 agent（stdio，**不带 `--runtime-provider`**，用它本机配好的默认模型）跑 pilot 全量 | 出分、schema 与现有 `submissions/*.json` 兼容、transcript 能被 `_summarize_transcript` 直接消费；且我们侧没有注入任何 `OPENAI_*`（跑之前把 shell 里的那些变量清空，跑完确认结果里没有我们填的模型 id） | 结果 JSON + job 详情 + 启动命令记录 | 待执行 |
| R2 | 真实服务通道 | 1,3 | 其中带附件的题（xlsx / png）走完整数据面 | fixture 下载命中 + 产物 PUT 回收 + 重建 workspace 参与判分，三段都有落盘记录 | artifacts 表 + workspace 快照 | 待执行 |
| R3 | 真实服务通道 | 4 | judge 撞免费档速率上限（429） | 指数退避重试；用尽记 `judge_unavailable`，不进 0 分、不改分母、在 `tasks_errored` 可见 | 重试日志 + 结果 JSON | 待执行 |
| R4 | 真实服务通道 | 2,6 | 同一 job 连跑两轮比分差 | 每轮 `judge_served_models` 有记录；两轮服务模型集合不同时，看板与报告标注"不可比"而不是并列成两列分 | 两轮结果 JSON 对比 | 待执行 |
| R5 | 真实服务通道 | 4 | 被测侧因**对端自己的配置**出问题（provider key 缺失 / 模型额度用尽 / 模型下线） | 失败原因能区分"远端拒执 / 对端模型不可用 / 速率限"，三者不共用一个 `failed`；对端配置类失败不记 0 分 | job_tasks 的 failure_reason 分布 | 待执行 |
| R6 | 真实服务通道 | 7 | 全链路 api_key 泄露扫描（结果 JSON、详情、报告四格式、服务日志） | 四处都不出现密钥或其前缀；judge 的 provider 配置只以 base_url 与 model id 出现，密钥字段名都不进结果 | 对产物做 `sk-or` 等前缀 grep 的输出 | 待执行 |
| R7 | 真实服务通道 | 2,10 | 被测模型标识的三态：能提取到 / 提取不到 / 两轮不同 | `subject_model_reported` 有值时看板概览与报告首屏显示它；提取不到时显示显式的"被测模型未知（由对端配置决定）"，**不能留白也不能用我们配置里的字符串顶替**；两轮不同时对比视图标注差异 | 三份样本（含 unknown 态）截图 + 结果 JSON | 待执行 |

## 3. 执行前提

- 假 ACP agent（已就位：`tests/cpd/acp_remote_eval/tools/fake_acp_agent.py`）：可脚本化扮演四种行为——正常回传（`--mode artifacts`）、零产物（`zero`）、拒收路径（`refused-paths`）、刷 stderr（`stderr-flood`）、挂死（`hang`）。它必须**真的按 manifest 里的 URL 下载 fixture、在本地目录里改文件、再 PUT 产物**，而不是直接返回一段写好的 transcript；否则 A5 与整组 E 用例检不出数据面的问题，而数据面正是 BYO 模式相对现有 CLI 唯一新增的东西。它同时必须**是一个真讲 ACP 的 stdio 进程**（用 `agent-client-protocol` SDK 实现，被 `RemoteAcpAgent` 像对待真 agent 一样拉起），而不是同进程里的函数桩——否则 transport 与 `session/update` 归一化这两段代码第一次被真正执行，就是拿真实 QwenPaw 联调的时候，那是最贵的一次。M1 第一件事就是它，否则所有远端用例都依赖真实外部服务，测试不可重复。
- **假时钟（已就位：产品代码 `service/schedule.py` 的 `Clock` / `FrozenClock` / `SystemClock`，不是测试目录里的桩）**：调度窗口与数据集用例必须能在毫秒级推进 `not_before` / `not_after` / tick，不允许用真实等待时间验证"00:00 起跑"。调度器的时间读取必须走注入的 clock 抽象，这条要在 M1 的代码结构里就定下来，事后补会牵动全部用例。
- 内置数据集 fixture：**已就位，但不落在 `fixtures/datasets/` 目录里**——由 `tests/cpd/acp_remote_eval/support.py::write_task` 按用例现场生成（front matter + `fixtures/` 下的字节文件），写进 `tmp_path`。理由是去重用例要的是"重叠的任意组合"，固定目录里的样本集迟早要为每个用例再加一份副本；代价是 J2/J3 的数据形状在读 `support.py` 时才看得清，不在磁盘上。不依赖 `data/pawbench-v1.0` 全量。
- pilot 数据集 fixture（约 15 题的 `task_ids` 显式清单，≥5 题 `workspace_files` 非空且 xlsx 与 png 各至少一个）：**未建，属 M2**。J9 断言与 A5 的真机版都吃这份，服务播种与测试校验必须用同一份数据，避免"测试过了但线上种子不满足"。M1 的 A5 用 3 题最小集（1 题无附件、xlsx 与 csv 各 1 题带附件）先验证数据面三段证据。
- 泄露扫描脚本（`tests/cpd/acp_remote_eval/tools/scan_shared_leakage.py`）：**已建**（M2 第六批，随 K2/F2 一起，见 §4.13）：两份字段表＋三组 label/heading/tag 正则只在这一点定义，K2 与 F2 经 `support.leakage_rules()` 读同一份，命令行也能单独跑（`python tests/cpd/acp_remote_eval/tools/scan_shared_leakage.py out/report.md`，有发现即退出码 1）。扫描对象是序列化后的响应体与落盘的渲染文件，不是数据库行——字段在聚合层被漏掉时，读库是检不出来的。**原判据里"两处规则不一致时，通过的那处不代表另一处安全"这一条现在由结构消掉**：`test_reports.py` 的档位字段表与 `test_no_tier_publishes_the_grading_code` 的字面量都换成了同一份集合常量，两条用例与命令行扫的是同一个词表，不存在"改了一处忘了另一处"。
- **真实服务通道（R 组，必跑）**：被测 agent 用本地 QwenPaw —— `{QwenPaw}/venv_312/bin/python -m qwenpaw acp --agent <id> --workspace <dir>`，**不带 `--runtime-provider`**（已定：被测用它本机配好的默认模型，我们不注入 `OPENAI_*`、不钉 model id）。judge 走 OpenRouter 免费档（`https://openrouter.ai/api/v1` + `openrouter/free`）。judge 密钥只从 `OPENROUTER_API_KEY` 环境变量读（本机来源是 `~/.qwenpaw.secret/providers/builtin/openrouter.json`，**不复制进仓库、不写进任何结果文件或日志**）。假 agent 保证用例可重复，真实通道保证"评的确实是别人那一整套"——只有假 agent 的测试等于用我们自己写的桩验我们自己写的逻辑，R 组缺失时 M2 不算出口达标。
- R 组的 `service.public_base_url` 保持 `localhost` 即可：stdio 拉起的 QwenPaw 与评测服务同机，fixture 下载可达。跨机跑真实远端时才需要换成对端可达地址（E7）。
- 每轮执行记录：日期、服务版本、commit、并发配置、`service.public_base_url` 与 `schedule.timezone` 配置、该被测 QwenPaw 的默认模型（本机 `qwenpaw` 配置里读，或按 R7 记 `subject_model_reported`）、`judge_model` 与该轮 `judge_served_models` 集合、判定结果、失败项 issue 号。模型字段必须记：被测侧现在是"对端那套配置"的快照，不记就分不清分数差是能力变化还是配置变化；judge 侧不记就分不清是判分尺度变了还是模型换了后端。
- 严重级问题（安全维度 7 任一条）未修不得进入下一阶段；M2 出口要求 R1/R2 通过（真实服务通道跑通 + 附件题三段证据齐），否则功能只在自写的桩上验证过；M3 上线前 D、E 组必须全绿，其中 E6（URL 不受 `Host` 影响）、R6（密钥不入产物与日志）与 F1（judge 注入）算安全硬门槛；I4/I5（窗口结束语义）、J5（数据集内容校验）、J9（pilot 附件题覆盖，覆盖不足则数据面根本没被验过）与 K2/K3/K4（`shared` 档泄露、档位不因调用者被静默降级、zip 与档位的组合按 400 拒）在同一门槛。H3（合并边界）不算上线门槛，但**从 M1 起每个里程碑提交前都要跑一次并贴输出**：它防的是"顺手在核心里加一行"，而这类改动一旦进来，下一次社区合并时才发现的人不是写它的人。

## 4. M1 执行记录

### 4.1 环境与命令

| 项 | 值 |
|---|---|
| 日期 / commit | 2026-11-10（Asia/Shanghai）／分支 `feat/acp-remote-eval`，基线 `d868ef5`，本特性文件全部未提交 |
| 解释器 | `/Users/anderson/Desktop/ClawParterner/.venvs/pawbench-eval/bin/python`（3.12.13） |
| 依赖版本 | fastapi 0.162.2、starlette 1.10.0、uvicorn 0.54.0、httpx 0.28.1、pydantic 2.14.3、`agent-client-protocol` 1.0.0、pytest 9.2.0、pytest-asyncio 1.4.1.post1 |
| 被测端 | `tests/cpd/acp_remote_eval/tools/fake_acp_agent.py`，独立进程、真 stdio ACP、真 HTTP |
| 服务地址 | `service.public_base_url = http://127.0.0.1:<临时空闲端口>`，每用例起一个真 uvicorn |
| 时钟 | 单元用例走 `FrozenClock(2026-11-10T02:00Z)`；端到端与数据面往返走 `SystemClock` |
| 并发配置 | `max_concurrent_jobs=4`（默认值本身，未在用例里改） |

```bash
$ <venv>/bin/python -m pytest tests/cpd/acp_remote_eval -q
348 passed, 1 warning in 12.09s
```

M1 收口时是 270（检视前 242 → 第一轮修复后 261 → 第二轮修复后 267 → 补上检视留出的三条空分支断言后 270），补测清单见 §4.6。M2 的常驻进程切片第一批加 63 项（270→333），第三轮检视修复再加 15 项（333→348）。按文件算，从切片第一批到现在：**`test_store.py` 19→22**（租约归属 + 批量 skip 2 项）、**`test_runtime.py` 21→24**（cancel 竞态、心跳与租约的先后、租约释放失败仍收尾）、**`test_runner.py` 32→34**（setup 卡死吃墙钟、collect 超界的分类）、**`test_config.py` 23→25**（`tick_seconds` 下限）、**`test_daemon.py` 15→20**（退出路径、死掉的调度器、URL 凭据脱敏）。M2 各批的用例见 §4.7 与 §4.8。那条 warning 是 starlette 提示 `TestClient` 的 httpx 依赖改名，与本特性无关，不处理。

同仓库其余测试：`pytest tests -q --ignore=tests/cpd` 在本 venv 只有 4 项可跑，`tests/test_grader_dependencies.py` 需要 `unified_planning`（本 venv 未装，属 PDDL 判分依赖，与本特性无关，见 §4.4 遗留）。

### 4.2 自动化覆盖（按 §2 的用例 ID）

| 用例 | 自动化位置 | 本轮结论 |
|---|---|---|
| A1 | `test_runner_e2e.py::test_a_real_agent_runs_three_builtin_tasks` | 通过（部分）：3 题全 `finished`、`artifacts=3`、`subject_models_reported=["fake-model-1"]`、attempt 全部注销。"出分与结果 JSON schema"要 M2 判分链路，本轮只到"交换完成" |
| A2 | `test_runner_e2e.py::test_an_unreachable_agent_fails_without_eating_the_timeout` | 通过（部分）：命令不存在 → `failed(acp_agent_not_found)`、耗时 <5s。HTTP 地址形态的 `acp_unreachable` 需要提交 API，M2 补 |
| A3 | `test_runner_e2e.py::test_an_agent_that_keeps_its_files_is_missing_not_failed` + `test_runner.py::test_three_kinds_of_result_stay_three` | 通过：`{"missing": 3}`、`failure_reason=no_artifacts`、`stop_reason=end_turn`、transcript 事件 >0 |
| A5 | `test_runner_e2e.py::test_the_attachment_task_shows_all_three_legs` | 通过：`session/fixtures/budget.xlsx` 落地、`uploads/output/budget.md` 回收、`workspace/` 重建、artifacts 表一行——三段证据同轮 |
| C1–C4 | `test_queue.py`（27 项） | 通过：并发上限、`queue_pos` 中点插队、running 拒调序、同用户限流；本轮加准入守卫与 cancel 竞态（§4.6） |
| D1、D2 | `test_auth.py`（10 项） | 通过（部分）：白名单外、过期、revoked 与日志脱敏（只 subject + hash 前 8 位）。D3/D4 是详情端点行为，M2/M3 |
| E1、E2、E3、E5、E6 | `test_exchange.py`（55 项）+ `test_data_plane_api.py`（16 项） | 通过：路径穿越/绝对路径/未声明前缀拒收、`conftest.py` 与 `.pth` 黑名单拒收、run token 跨 task 与 TTL、`Host` 不参与 URL 拼装；本轮加额度与并发花费（§4.6） |
| E7 | `test_config.py`（25 项） | 通过（部分）：`public_base_url` 缺失即启动失败并指名配置项。`assets_unreachable` 与 `agent_refused` 的诊断分档要真实远端，M2 |
| I1–I8 | `test_schedule.py`（21 项）+ `test_queue.py` | 通过：三种窗口、23:40 不足 30 分钟、窗口关闭语义、scheduled 不占并发位、跨日/DST 边界 |
| J1–J7、J10 | `test_datasets.py`（32 项） | 通过：内置视图解析、混合选择去重、快照复现、owner 收紧、分类名规范化、引用计数 409；本轮加分类归属与包体积/收集器政策（§4.6） |
| — | `test_store.py`（22 项） | 通过：JSON 列类型往返、job_tasks 行、队列位点、`transition_job` 守卫、`admit_job` 相关子查询；M2 加租约 6 项（占有／刷新／越界拒／beat 不越主／孤儿清单／一次性 settle） |
| — | `test_runner.py`（34 项） | 通过：计划按快照、双 dataset 命中去重、fixture 位置、无快照拒跑、重试自成一行、`collect_timeout` 与 `interrupted` 两个码；M2 加作业墙钟 4 项（见 §4.7） |
| — | `test_runtime.py`（24 项，M2 新增） | 通过：见 §4.7 的 S6/L9 行 |
| — | `test_daemon.py`（20 项，M2 新增） | 通过：见 §4.7 的常驻入口行 |
| — | `test_acp_client.py`（31 项） | 通过：endpoint 校验、transport 路由、权限自动批准与计数、`fs/*`+`terminal/*` 一律 method_not_found、stderr 有界尾巴、握手不回应 30 秒内判 `acp_handshake_timeout` |
| — | `test_acp_transcript.py`（23 项） | 通过：`session/update` 归一化成 `_summarize_transcript` 能吃的形状、`_meta.model` 提取 |
| C5、C6、A4、B*、F*、G*、H1、H2、I*（进程级）、J8、J9、K*、R* | 未执行 | 常驻入口与租约本轮已就位（§4.7），这些用例还差提交 API（`POST /v1/jobs`）、详情端点、判分链路、看板与真实 QwenPaw 通道 |

### 4.3 H3 合并边界（M1 提交前，原样输出）

```bash
$ git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt
（空——上面这一行没有输出，就是"核心零改动"这条判据本身）

$ git status --porcelain -uall -- pawbench tests | grep -v __pycache__
?? pawbench/cpd/__init__.py
?? pawbench/cpd/acp_remote_eval/README.md          # 安装与"还不能跑"的说明
?? pawbench/cpd/acp_remote_eval/__init__.py
?? pawbench/cpd/acp_remote_eval/__main__.py         # 常驻入口的命令行
?? pawbench/cpd/acp_remote_eval/acp/__init__.py
?? pawbench/cpd/acp_remote_eval/acp/client.py
?? pawbench/cpd/acp_remote_eval/acp/transcript.py
?? pawbench/cpd/acp_remote_eval/harness.py
?? pawbench/cpd/acp_remote_eval/requirements.txt
?? pawbench/cpd/acp_remote_eval/service/__init__.py
?? pawbench/cpd/acp_remote_eval/service/api.py
?? pawbench/cpd/acp_remote_eval/service/auth.py
?? pawbench/cpd/acp_remote_eval/service/config.example.yaml
?? pawbench/cpd/acp_remote_eval/service/config.py
?? pawbench/cpd/acp_remote_eval/service/daemon.py   # 装配 + 启动/退出顺序
?? pawbench/cpd/acp_remote_eval/service/datasets.py
?? pawbench/cpd/acp_remote_eval/service/exchange.py
?? pawbench/cpd/acp_remote_eval/service/queue.py
?? pawbench/cpd/acp_remote_eval/service/runner.py
?? pawbench/cpd/acp_remote_eval/service/runtime.py  # 租约 / reconcile / 调度循环
?? pawbench/cpd/acp_remote_eval/service/schedule.py
?? pawbench/cpd/acp_remote_eval/service/store.py
?? tests/cpd/acp_remote_eval/conftest.py
?? tests/cpd/acp_remote_eval/support.py
?? tests/cpd/acp_remote_eval/test_acp_client.py
?? tests/cpd/acp_remote_eval/test_acp_transcript.py
?? tests/cpd/acp_remote_eval/test_auth.py
?? tests/cpd/acp_remote_eval/test_config.py
?? tests/cpd/acp_remote_eval/test_daemon.py
?? tests/cpd/acp_remote_eval/test_data_plane_api.py
?? tests/cpd/acp_remote_eval/test_datasets.py
?? tests/cpd/acp_remote_eval/test_exchange.py
?? tests/cpd/acp_remote_eval/test_queue.py
?? tests/cpd/acp_remote_eval/test_runner.py
?? tests/cpd/acp_remote_eval/test_runner_e2e.py
?? tests/cpd/acp_remote_eval/test_runtime.py
?? tests/cpd/acp_remote_eval/test_schedule.py
?? tests/cpd/acp_remote_eval/test_store.py
?? tests/cpd/acp_remote_eval/tools/fake_acp_agent.py
```

计数（第三轮检视修复后重跑，非 M1 时的清单）：`pawbench/cpd/**` 22 个文件（19 个 .py + `requirements.txt` + `README.md` + `config.example.yaml`），`tests/cpd/acp_remote_eval/**` 17 个 .py（含 `tools/fake_acp_agent.py`），合计 **39 个新增文件**，全部在两处 `cpd/` 之下；`__pycache__` 已被仓库忽略规则排除在本清单之外。相比 M1 的 33 个，多出的 6 个是 M2 常驻切片的 `__main__.py`、`config.example.yaml`、`daemon.py`、`runtime.py` 与 `test_daemon.py`、`test_runtime.py`。

结论：新增文件 100% 落在 `pawbench/cpd/acp_remote_eval/**` 与 `tests/cpd/acp_remote_eval/**`；`pawbench/agents/factory.py`、`run_bench.py`、`pyproject.toml`、`requirements.txt`、`data/pawbench-v1.0/**` 零改动。依赖改由 `pawbench/cpd/acp_remote_eval/requirements.txt` 声明，比 design §2.1 原计划的"共享文件加一处依赖块"更干净——社区侧合并时与本特性无关的文件一个都不碰。

三轮检视修复之后重跑同样两条命令，输出与本节一致：核心零 diff（第一条命令无输出），未跟踪文件 39 个——M2 之后没有再新增文件，只改了既有文件。仓库根本地改动只有 `.gitignore` +4 行（忽略 `service/runtime/` 运行目录），不含任何核心源码。

### 4.4 本轮发现并已修的缺陷

四个都只有真进程 + 真 socket 才暴露，in-process 桩按构造看不见——这正是 §3 要求假 agent 必须是独立进程的原因。

| # | 现象 | 根因 | 处理 |
|---|---|---|---|
| 1 | 5×404，fixture 全部拉不到 | `ASSET_ROUTE` 的 `{dest}` 不跨 `/`，而 `Exchange.asset_url` 保留斜杠签名 | `api.py` 路由改 `{dest:path}`，并在注释里把两处绑在一起 |
| 2 | 无附件任务直接崩 `TypeError` | `TaskLoader` 对没有 fixture 的题留 `workspace_files=None`，manifest 构造当成可迭代对象 | `exchange.py` 新增 `_fixtures_of()`，三处迭代统一走它 |
| 3 | 两个带附件题报 `acp_connection_lost` | prompt block 用了 `ResourceLink` 基类，SDK 的 union 只收 `ResourceContentBlock` | `harness.py` 换类型；并加 `ValidationError → acp_prompt_rejected` 分支，本地序列化错误不再冒充"连接断了" |
| 4 | `missing` 行 `failure_reason` 为空 | 交换本身成功，没有错误码可带，报告里读起来像"没记录" | `runner._record` 对 `missing` 写 `no_artifacts`，行与 payload 同步 |

另外两处不是缺陷，是行为澄清，已固化进测试：`JobRunner` 的计划顺序是"数据集按 id 字典序 + 快照内原序"（`test_runner.py::test_a_task_named_by_two_datasets_runs_once`），以及 `no_artifacts` 与 `failed` 必须是两个状态（`test_three_kinds_of_result_stay_three`）。

### 4.5 遗留

| 项 | 责任人 | 期限 |
|---|---|---|
| `tests/test_grader_dependencies.py` 需要 `unified_planning`，本 venv 未装，M1 未跑该仓库测试 | anderson | M2 首轮回归前，用仓库正式环境跑一次全量 |
| 常驻服务入口（config → app + tick 循环 → `JobRunner`）尚无代码，`JobQueue.tick()` 的返回目前只被单元测试消费 | anderson | **已交付（M2 第 1 项，见 §4.7）**：`daemon.py` + `runtime.py` + `__main__.py` + `config.example.yaml` |
| R 组真机通道（pilot 种子与 `scan_shared_leakage.py` 已在 §4.10／§4.13 交付） | anderson | M2 出口（R1/R2 是硬门槛） |
| stdio 本地产物回收通道与路径收敛（`additional_directories` 目前只是声明） | anderson | M2 |
| 独立检视一般／建议项 L1–L8、L11–L15（窗口关闭刷日志、`normalize_positions` 单事务、GET 路由 IO、流式 hash 与保留策略、grant 索引、包校验两趟、白名单指纹与空读、`stderr_tail` 脱敏、全行拉取与无 LIMIT 的计数、`shield` 后台写无人 await、告警双份与 `repr` 丢栈、周期租约清扫、优雅退出的原因码语义）| anderson | 见 `review_acp_remote_eval.md` 各轮复检的遗留表。L9（job 级墙钟）与 S6（重启 reconcile／lease）已随 M2 第 1 项交付并关闭 |
| L10 超宽 **49 行 / 16 文件**（M1 时 38 行，M2 切片带来 11 行）需单独一次纯格式化提交，不与逻辑改动混在同一个 commit | anderson | M1 提交前（第三轮检视前后新增的 15 项用例与 5 个源文件改动均在 100 字符内，已逐行统计核对） |

### 4.6 检视补测（钉住修复行为的用例）

§4.4 是首轮真进程暴露的缺陷；这一节是两轮独立检视（`review_acp_remote_eval.md`）改完之后，为防止"修复本身退回去"而补的用例。每条都能在旧实现上失败，除 R7 一处已注明。

| 检视项 | 用例 | 钉住的行为 |
|---|---|---|
| R1/R2（S5 延伸） | `test_queue.py::test_a_cancel_between_insert_and_admit_is_not_overwritten` | 行写入与准入之间落地的取消不会被覆盖回 queued；`admit(..., from_status="new")` 失败即 `job_not_admissible` |
| S5 | `test_store.py::test_transition_job_only_moves_the_state_it_expected`、`test_admit_job_counts_the_running_set_inside_the_statement`、`test_admit_job_holds_the_per_user_limit`、`test_admit_job_never_revives_a_canceled_job` | 状态迁移带 `WHERE status = ?` 守卫；两条限额在单条语句内计数，不靠调用方传 submitter（R4） |
| R5 | `test_exchange.py::test_checking_a_token_leaves_the_whole_budget_intact` | 只验证不消费：`check_run_token()` 之后额度分文未动，因此可以在读请求体之前先拒 |
| R6 | `test_exchange.py::test_a_refused_upload_does_not_cost_the_run_a_slot` | 路径/体积不合格 PUT 被拒后，真正的答案仍能上传——花费额度发生在落盘之后 |
| R7 | `test_exchange.py::test_a_single_upload_slot_is_not_spent_twice_by_two_threads` | 16 线程抢同一个上传额度，只有 1 次成功。**诚实标注**：无锁版本在 GIL 下通常也能过，属回归防护而非鉴别性测试 |
| R8 | `test_exchange.py::test_a_recorded_artifact_that_is_missing_fails_the_rebuild`（改写） | 库里有、盘上没有的 artifact 抛 `artifact_missing`，不再打一行 warning 后把空目录交给判分 |
| R11 | `test_acp_client.py::test_an_agent_that_never_takes_the_handshake_does_not_hold_the_slot` | 起了进程不说话 → 0.05s 内 `acp_handshake_timeout`（生产默认 30s），不再无限占槽位 |
| R3/R11 | `test_runner.py::test_a_cancelled_attempt_is_recorded_instead_of_staying_running`、`test_an_attempt_we_could_not_assemble_is_not_a_runner_error` | 取消必须自己写行（`interrupted`），collect 超时是 `collect_timeout` 而不是混进 `runner_error`——两条都是"改回旧写法就会失败"的鉴别性用例 |
| R12 | `test_datasets.py::test_assign_categories_updates_counts`（加陌生人拒绝断言） | 分类改动走与 `delete_dataset` 同一 owner-or-admin 规则，新建分类记在操作人头上 |
| R13 | `test_datasets.py::test_a_test_module_in_the_package_is_refused`、`test_an_oversized_package_is_refused_before_anything_is_read` | `test_*.py` / `*_test.py` 在判分机上会被 pytest 收集执行 → 直接拒；文件数/字节数上限在读第一个文件之前生效 |
| S1（并发面） | `test_exchange.py` 的额度用例 + `test_queue.py::test_a_cancel_that_lands_mid_tick_is_not_revived` | 后者的 monkeypatch 仍按函数名注入（改 patch `update_job` 需要先把 admit 退回无守卫写法，不做） |

### 4.7 M2 第一批：常驻进程切片（租约、重启、墙钟、入口）

检视遗留表里 L9 与 S6 被钉成「同批交付」——常驻入口与 reconcile 缺一不许合入。这一批就是那一批，交付物是 `service/runtime.py`、`service/daemon.py`、`__main__.py`、`config.example.yaml` 与 `store.py` 的 `job_leases` 表。

| 检视项 / 用例 | 自动化位置 | 钉住的行为 |
|---|---|---|
| S6（租约） | `test_store.py`：`test_only_the_lease_owner_can_refresh_it`、`test_the_stale_boundary_is_exclusive`、`test_a_beat_or_release_never_touches_another_owners_row`、`test_orphan_running_jobs_lists_only_unbeaten_rows`、`test_settle_orphan_job_writes_job_tasks_and_lease_once`、`test_a_second_settle_changes_nothing` | `running` 行到底有没有活人：beat 只认同一 owner，TTL 边界Exclusive（等于 TTL 即失效），孤儿清单不牵连 `queued`，settle 是「一次写、写三处（job／task／lease）」 |
| S6（重启） | `test_runtime.py`：`test_reconcile_settles_a_job_the_previous_process_left`、`test_reconcile_is_idempotent`、`test_a_live_foreign_lease_survives_reconcile` | 重启不把还在跑的别人家任务判死；不把死任务自动重跑（workspace 还在盘上，重跑会把半写文件当自己的输出评） |
| L9（作业墙钟） | `test_runner.py`：`test_the_wall_clock_labels_tasks_it_never_reached`、`test_the_time_left_becomes_this_attempt_s_timeout`、`test_the_cap_never_hands_the_agent_a_zero_timeout` | 到点不是「少评几题」而是每行都写 `skipped(deadline)`；剩余时间进 attempt 内部（不是只在题与题之间检查），且绝不传给 agent 一个 0 秒超时 |
| S6（租约丢失／冲突） | `test_runtime.py`：`test_losing_the_lease_stops_the_run_and_labels_it`、`test_launch_refuses_a_job_another_process_holds` | 丢租约时立刻停手并把行写成 `lease_conflict`；本机计数说有空位、别人的租约说没空位时，以租约为准（不重复跑同一个 job） |
| I5（窗口结束语义） | `test_runtime.py`：`test_a_window_that_closed_while_queued_fails_once`、`test_a_hard_stop_closes_the_window_and_labels_the_tasks` | 窗口关闭不会被每个 tick 反复报「还在等」；`hard_stop` 关掉的运行不留 `pending` 行 |
| 作业行归属 | `test_runtime.py`：`test_a_run_that_raised_leaves_the_job_failed_not_running`、`test_a_finalizer_does_not_revive_a_canceled_job`、`test_the_outcome_uses_the_rows_not_the_run` | `runner` 一律不碰 job 行，job 行由 runtime 依 task 行推出；cancel 已经写过的行不会被收尾写回活状态 |
| 常驻入口 | `test_daemon.py`（20 项） | 配置项真的传到执行者（`max_job_seconds`→runner、`lease_ttl`/`tick`→runtime、并发→queue）；数据面 app 与 runtime 共用同一个 `Exchange`/registry；启动顺序是 reconcile 在开端口之前；退出路径关库；`--config` 与日志级别真的生效 |
| E7（配置不变式） | `test_config.py`：`test_a_lease_shorter_than_two_ticks_is_refused`、`test_the_two_tick_boundary_is_accepted`、`test_a_job_with_no_wall_clock_is_refused`、`test_the_shipped_example_config_parses`、`test_the_example_paths_reach_the_real_corpus` | 一个 tick 内就会过期的租约在启动期拒绝（settle 不可逆）；随包发布的示例配置能被 `load_config` 读，并且指向真实存在的题库 |
| 日志（规范第 2 条） | `test_daemon.py::test_the_entry_point_renders_the_context_the_package_logs` | 全包的上下文走 `extra=`，默认 formatter 会静默丢掉——入口换成 `ContextFormatter` 后，`job launched` 才真的带着 `job_id` 与 `owner` |

本轮由「写用例」发现并修掉的真缺陷一处：运行被停掉（硬停／窗口关闭）时，`_finalize` 只写了 job 行，没被触及的 task 行留在 `pending`，与 design §5.2「`skipped(window_closed)`」不符。改法是 runtime 记住每次停止的原因（`_stops`），收尾时先把 `pending` 标掉再推 job 行；提交者自己 cancel 的情形读 job 行里已有的原因。

### 4.8 M2 第二批：第三轮检视的修复（调度器存活、attempt 墙钟、退出路径）

第三轮独立检视（`review_acp_remote_eval.md` §复检记录第三轮）针对常驻切片提出 M1–M13：2 条严重、7 条一般、4 条建议。严重两条都属「服务看起来活着，其实已经不干活了」，一般七条与建议里的 M10 当场修，其余三条建议加两条语义待定项进遗留。下表除 M8 外，每条右边的用例都是**把修复分支删掉就会红**的鉴别性用例，M4 另做过一次"移除守卫 → 用例失败"的实测反向验证。

**M8 是个例外，如实记下**：`reconcile` 与 `_cut_short_reason` 改走 `asyncio.to_thread` 之后，现有用例仍然全部通过——单线程用例看不出一次同步 SQLite 调用有没有占住事件循环，把 `to_thread` 拆掉它们照样绿。这一条目前只有契约文字（`store.py:7-8`、`runtime.py:105-108`）与代码评审兜着，缺一个「让 store 的一个查询睡 50 ms、同时另起协程探活」的循环卡顿回归用例。它和 §2 里 I 组没有覆盖的"数据面与调度共用一个循环"是同一个缺口，随提交 API（数据面真的和调度器同进程活了）一起做，进检视遗留 L11 同批。

| 检视项 | 修复位置 | 用例 | 钉住的行为 |
|---|---|---|---|
| M1（严重） | `config.py:190`、`runtime.py:183`、`daemon.py:193` | `test_config.py::test_a_scheduler_that_never_sleeps_is_refused`（`tick=0`／`-0.5`） | `tick_seconds` 为 0 不是「一直 tick」而是「从不让出」，会在启动期被拒；`sleep` 移进守卫后，一次 tick 之间的异常不能终结循环；退出时调度器**自己**死掉要打 error 并带 `reason`，被取消才是 info。用例断的是 `record.reason` 里有调度器抛出的那句异常 |
| M2（严重） | `runner.py:133`、`runner.py:342-372` | `test_runner.py::test_an_agent_that_never_finishes_the_handshake_loses_the_jobs_time`、`test_runner.py::test_a_collect_that_outlives_its_own_bound_is_still_our_fault` | setup / prompt / collect 三步共用一个 `asyncio.timeout` 窗口：远端接了连接却不完成握手，1.5 s 墙钟内落定为 `failed(deadline)` + 后续 `skipped(deadline)`，实测 elapsed < 3 s，日志带 `stage='setup'`；而 collect 超界是 `collect_timeout`——那是我们的机器坏了，不是对方慢。两条分别要求删掉 `deadline` 分支与 `stage=='collect'` 分支才会红 |
| M3（一般） | `store.py:681` `skip_unrun_tasks()` | `test_store.py::test_skipping_unrun_tasks_labels_only_what_never_started`、`test_store.py::test_skipping_is_scoped_to_the_attempt_it_was_asked_for` | 一条 UPDATE 取代逐行写：`running`／`finished` 行不动、被标掉的行 `duration_s == 0.0`、给了 `attempt` 就只标那一轮。`settle_orphan_job` 保持原样（本就批量、且与另两条写同事务、覆盖面含 `queued`） |
| M4（一般） | `runtime.py:286-292` | `test_runtime.py::test_a_lease_release_that_fails_still_closes_the_job_row` | 释放租约抛 `sqlite3.OperationalError` 时，job 行仍被收尾成 `finished`，且日志留下「lease release failed」。反向验证：临时移除守卫 → 该用例以 `OperationalError` 失败；恢复 → `test_runtime.py` 24 passed |
| M5（一般） | `runtime.py:412`、`runtime.py:430` | `test_runtime.py::test_a_canceled_job_is_not_relabelled_when_its_window_closes` | 窗口关闭与 cancel 抢同一行时，提交者的 `canceled` 赢：`_window_closed` 返回 False，`status` 与 `error` 两列一个字都不改 |
| M6（一般） | `daemon.py:178-190` | `test_daemon.py::test_an_exit_step_that_raises_does_not_skip_the_others` | `runtime.shutdown()` 抛异常时，停调度与关库两步照做，并各打一条带 `step` 的 error——退出路径是这些行唯一的写入者，一步失败不能带走后两步 |
| M7（一般） | `runtime.py:279-285` | `test_runtime.py::test_the_beat_loop_is_stopped_before_the_lease_is_released` | 事件顺序必须是 beat-start → beat-stop → release：心跳只 cancel 不 await，会让一次在途 `beat_lease` 落在 release 之后，把别人刚拿到的租约又续成"我的" |
| M8（一般） | `daemon.py:153`、`runtime.py:322` | `test_daemon.py`（启动顺序用例覆盖 reconcile 在开端口之前）、`test_runtime.py`（收尾用例读 `_cut_short_reason`）| `Store` 是同步的，全表 orphan 查询与收尾时的 `get_job` 都必须离循环——否则启动与收尾两处各卡住整个进程 |
| M9（一般） | `store.py:380`、`runtime.py:228` | `test_store.py::test_the_lease_owner_is_named_for_the_process_that_lost_the_race`、`test_runtime.py::test_launch_refuses_a_job_another_process_holds`（加断言） | 被拒的一方要能说出"谁占着"：日志同时带 `owner='proc-a'`（被拒的）与 `held_by='proc-b'`（占着的）——这是为「两个服务指向同一个库」准备的唯一现场证据 |
| M10（建议） | `daemon.py:48`、`daemon.py:73` | `test_daemon.py::test_the_renderer_does_not_pass_a_credential_in_a_url_through` | 提交方 token 可以骑在 URL 的 userinfo 里，而库会把失败的那次请求原样复述：渲染出口把 `scheme://user@host` 折成 `scheme://***@host`，同时保留 `127.0.0.1:9100/rpc`——host 才是"哪个 agent"的定位信息 |

### 4.9 本轮自查发现并清掉的一处重复定义

`service/store.py` 里 `lease_owner()` 有两份完全相同的定义（380 与 681），是修复过程中一次编辑方向写反留下的。因为函数体一致，后定义静默覆盖前定义，**348 项测试全绿也照不出来**——它不是运行期缺陷，是下一个人改其中一份时才会踩的坑。已删除第二份，保留与 `acquire／beat／release_lease` 同组的那一份；删除前后各跑一次全量，均为 348 passed，可反证两份确实等价。随后用 AST 扫全包类内重名方法，除 `BuiltinCatalog.tasks`（property + setter，合法）外无同类问题。

### 4.10 M2 第三批：控制面 HTTP API 全量（提交 / 数据集 / 详情 / 报告）

M2 的 API 层从"没有路由"到"25 条路由"（数据面 3 条 + `/healthz` + 控制面 21 条，见 `service/api.py`），一次补齐四个文件。命令与环境同 §4.1，解释器不变：

```bash
$ <venv>/bin/python -m pytest tests/cpd/acp_remote_eval -q --tb=line
517 passed, 1 warning in 15.18s
```

计数轨迹 348 → 517（+169），全部来自新增的四个文件与随后的 CLI 一批：**`test_jobs.py` 35**（提交契约与队列语义）、**`test_control_api.py` 38**（鉴权闸、状态码、列表／调序／取消的 HTTP 形状）、**`test_reports.py` 32**（两档详情、四格式报告、签名链接）、**`test_datasets_api.py` 30**（数据集与分类的九条路由，含 zip 上传；第十条 `POST /v1/datasets/resolve` 是预览语义，归在 `test_control_api.py`）。第四批的 `test_cli.py` 17 项与 `test_pilot.py` 17 项见 §4.11 与下表。

关掉的 §2 用例（判据以矩阵右边"判定"列为准，"通过（部分）"是真话而不是收尾）：

| 用例 | 自动化位置 | 结论 |
|---|---|---|
| B2 | `test_datasets_api.py::test_a_package_that_fails_validation_is_refused_item_by_item` | 通过：缺 `## Prompt`／缺 `grading_type` 逐条回到 `validation_report`，且 `test_a_refused_package_leaves_nothing_registered_or_unpacked` 断言拒收后既没注册也没落盘 |
| B1 | 同上（`test_an_uploaded_package_becomes_a_selectable_dataset`） | 通过（部分）：服务端一侧的校验—注册—可选全链路绿；"skill 准备的包"那一半要 M4 的 skill 就位才能按矩阵原样跑 |
| C2、C3、C4 | `test_control_api.py::test_a_queued_job_moves_by_queue_pos`、`test_a_running_job_says_to_cancel_instead_of_reordering`、`test_a_subject_at_its_running_cap_is_bounced_with_the_cap` | 通过：调序要恰好一个目标位、running 拒调序并指路 cancel、同用户上限在**写任何行之前**回答 |
| D1、D2、D3、D4 | `test_control_api.py`（401 三态 + `test_no_control_route_answers_without_a_token` + `test_one_subject_sees_another_subjects_jobs`）、`test_datasets_api.py::test_every_catalogue_route_refuses_an_absent_token`、`test_reports.py::test_detail_routes_over_http_match_the_object_level_ones` | 通过：白名单外与缺失都是 `401 unauthenticated`（不给"存在但不属于你"的差异，D4 的枚举口因此不存在）。D1 的"一条闸"由 `test_no_control_route_answers_without_a_token` 从 `client.app.routes` 反读挂载表逐条打 401（21 条控制面路由，数据面三条按 run token 排除），所以**将来加一条忘记鉴权的路由会在这里红**，而不是在某份没人更新的路由清单里绿着 |
| J1–J7、J10 | `test_jobs.py`（35 项全部）、`test_datasets_api.py`、`test_pilot.py::test_the_seed_covers_the_fixture_kinds_its_comments_claim` | 通过：快照与预览一致（`test_a_dataset_widened_after_the_preview_does_not_widen_the_job`）、分类展开带出提交人没点名的集、共用任务在两处 `requested_by` 下各记一次而分母只算一次；改／删收紧到 owner-or-admin（J4） |
| J9 | `test_pilot.py`（17 项） | 通过：种子自评不过时**拒绝就绪并把缺口列成清单**（`test_the_service_refuses_to_start_on_a_seed_it_cannot_honour`），附件形态覆盖数由 `test_the_seed_covers_the_fixture_kinds_its_comments_claim` 钉住，不靠注释自觉 |
| K1–K7、K9 | `test_reports.py` | 通过：`shared` 显示 prompt 隐藏 rubric、两档都不发判分源码、档位拼错是拒不是默认、`zip`+`shared` 走 400（K4）、报告在数字不动时复用同一份（K5 的 sha 可复现）、数据集消失仍出可读报告（K6 的 `stale_before` 语义）、未完成态不空结构（K7） |
| K8、K10、C5、C6、E4、E7、F1、G*、H1、H2、R* | 未执行 | 分页与流式的内存曲线、看板、进程级重启恢复、 asset 枚举限速、真机判分与插件都要真实进程或真实对端，不在这一批 |

本轮自查发现并修的两处（都是"实现少了一半规则"，不是测试写错）：

1. **`PUT /v1/datasets/{id}` 把 D15 的"改"那一半漏了**。路由原先直接落到 `create_builtin_view`，结果陌生人改别人的视图会得到 `409 dataset_exists`（把它当成"新建重名"），管理员改则会悄悄把 owner 换成自己。修法是把归属判定收进 `DatasetService.edit_builtin_view`（`not_dataset_owner` → 403），owner 用**存着的那个**而不是调用者，路由只做鉴权与转发——同一套规则 HTTP 侧和将来的 MCP 侧共用一份，不出现"curl 被拒、skill 能改"。用例：`test_recutting_someone_elses_view_is_refused`、`test_an_admin_may_recut_it`。
2. **zip 的唯一根可以是 `..`**。`zip -r ../x .` 写出的包，顶层目录就是 `..`；旧的 `_common_zip_root` 会把它当"共同的顶层目录"剥掉前缀，于是 `../escape.md` 变成 `escape.md` 里看似安全的名字，穿越守卫看不到原始名，报的是 `422 package_invalid` 而不是 `400 package_unsafe_path`。现在 `..` 明确不算根，守卫拿到归档里的原名。用例：`test_a_member_that_walks_out_of_the_package_is_refused`。

H3 合并边界在这一批之后重跑，输出仍为空（`git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 无输出）；新增文件按目录归类 **51 个**：`pawbench/cpd/acp_remote_eval/**` 28 个（25 个 .py + `README.md` + `requirements.txt` + `service/config.example.yaml`），`tests/cpd/acp_remote_eval/**` 23 个 .py。`pawbench/agents/factory.py`、`run_bench.py`、`data/pawbench-v1.0/**` 零改动。

### 4.11 M2 第四批：CLI 提交路径（`python -m pawbench.cpd.acp_remote_eval.cli`）

D23 说本地命令行提交走这个入口而不是 `run_bench.py --agent acp`，所以它得有自己的一批用例。做法是 `cli.EvalClient` 用真 `httpx.Client`，测试把 transport 换成 `httpx.MockTransport`，handler 里桥到真 FastAPI 的 `TestClient`（`support.cli_transport`）——`ASGITransport` 只有异步实现，而 `EvalClient` 是同步的。这样 CLI 不可能"对着一个服务已经不再提供的请求形状通过"。

`test_cli.py` 17 项里承担判据的：

| 判据 | 用例 |
|---|---|
| token 只骑 `Authorization` 头，不进 URL、不进输出 | `test_the_token_rides_one_header_and_never_a_url`（对每个 `httpx.Request` 断 `TOKEN not in str(request.url)`、头值恰为 `Bearer <token>`）、`test_a_refusal_comes_through_as_the_services_words`（400 的 `code` 原样引用，stderr 里不含明文） |
| 缺 token／未知 token／服务不可达三态各有各的文案与退出码 | `test_a_missing_token_is_refused_before_the_network`（`len(seen) == 0`，本地拒并指名 `$PAWBENCH_EVAL_TOKEN`）、`test_a_token_not_on_the_list_quotes_the_services_code`（`401 unauthenticated`，不回显 token）、`test_a_service_that_is_not_listening_says_so` |
| 提交的是服务认得的形状，不自己重算规则 | `test_submit_queues_what_the_service_resolves`（存 fingerprint + 快照，且 `list_job_tasks` 为空）、`test_submit_offers_the_selector_the_api_takes`（`requested_by == "category:email"`）、`test_an_empty_selector_is_refused_by_the_service_not_here`、`test_a_malformed_fingerprint_pair_is_refused_locally` |
| 队列满了是等待而不是拒绝 | `test_a_full_service_queues_the_job_instead_of_bouncing_it` |
| 读回三件事：状态、档位、报告 | `test_status_flags_the_tasks_that_did_not_work`（没问题的任务不占一行）、`test_status_can_hand_the_payload_to_a_script`（`--json --out`）、`test_detail_sends_the_tier_it_was_asked_for`（`sensitivity == "full"`）、`test_report_downloads_what_the_service_described`（下载后按 `link["sha256"]` 校验） |
| watch 的两条退出：自己到点 vs job 到终态 | `test_watch_stops_when_its_own_clock_runs_out`（`EXIT_TIMED_OUT`，job 不动、提示仍在排队）、`test_watch_prints_a_terminal_state_once` |
| 退出码可被 CI 用 | `test_watch_reports_a_canceled_job_as_not_ok`（`EXIT_JOB_NOT_OK`） |

本轮一处语义被自己的用例抓回来：`_report_job` 原本把"状态不是 finished 的任务"全当故障逐行打印，于是还没跑到的 `pending` 行也在报错误。原因是**提交时只存数据集快照，任务行是 runner 起跑才写的**（`test_jobs.py::test_listing_carries_no_task_rows` 早就钉住了这条），CLI 作为客户端不能假设两者同时存在。改成排除在途态 `_IN_FLIGHT_STATUSES = ("pending", "running")`，概览行仍照原样统计它们；这两个字符串写在 `cli.py` 而不是从 `service.runner` 导入，是为了不让 ACP 协议与 judge 客户端出现在 `--help` 的导入链上。

真机与端到端：本批没有起真服务，CLI 与 API 的往返在 `MockTransport` 上完成；`--server` 指向真常驻服务的实测随 R 组一起做（遗留 14）。

### 4.12 M2 第五批：第四轮检视的 6 条严重项 + 1 条自查

检视记录见 `review_acp_remote_eval.md` 第四轮（N1–N7）。这一批的测试不是新功能用例，而是**把七条已经改的行为钉成"删掉修复就会红"的断言**，共 6 条新用例 + 4 条改写/加固：新用例里有 5 条对号下表 N1–N7，第 6 条（`test_cli.py::test_a_service_that_names_a_path_for_its_file_does_not_choose_where_it_lands`）钉的是一般项里唯一顺手修的那条——服务返回的 `filename` 只取 basename，落盘位置由调用方定，它不在七条之内是因为严重度判的是"一般"。

| # | 修复 | 用例 | 断的是什么（为什么它鉴别修复） |
|---|---|---|---|
| N1 | 下载预签名链接不 accompanying bearer，异常文案不带 query | `test_cli.py::test_report_downloads_what_the_service_described`（加固）、`test_a_broken_download_does_not_quote_the_presigned_link`（新） | 前者对**下载那一笔**请求断 `"authorization" not in headers`——只断"bearer 不进 URL"的旧用例区分不了匿名 client 与复用主 client；后者让传输层抛一条把整条 URL 抄进消息的异常，断 sig 值、token 明文、`sig=` 三种形态都不进 stderr，而 `/v1/reports/` 还在（不是把错误吞掉） |
| N2 | 同 owner 也不能跨 kind 改造已有 dataset | `test_datasets_api.py::test_an_upload_and_a_view_cannot_cross_over_the_same_owner`（新） | 先建 view 再传 package、反过来再来一次，两个方向都断 `400 dataset_kind_fixed`，然后读两行的 `kind` 确认没被换——只断状态码区分不了"拒绝"和"先写后拒" |
| N3 | zip 流式落盘、按路径打开，体积闸在路由上 | `test_datasets_api.py::test_an_archive_over_the_quota_is_refused_before_it_lands`（加固） | 补两条：`"is over" in message`（只有路由的 `Content-Length` 预检会说这句话，unpacker 说的是 "declares"/"while unpacking"）与 `GET /v1/datasets/big` → 404（什么都没落库）。同时路由改为运行期经模块属性读 `MAX_PACKAGE_BYTES`，`monkeypatch` 才真的命中它声称的那道闸——这正是检视者指出的一处"用例名与实际校验不是同一处" |
| N4 | job 行与数据集快照同事务 | `test_store.py::test_a_job_and_its_snapshot_arrive_together_or_not_at_all`（新）、`test_jobs.py::test_a_submission_that_cannot_write_leaves_no_row_to_close`（改写） | 前者用 `dict(snapshot, requested_by={"not": "a string"})` 让第二条语句在绑参时失败，断 `get_job is None` **且** `list_job_datasets == []`（只断 job 行区分不了"回滚"和"从没写"），再断成功往返；后者从"留下一行 failed"改成"库里一行都没有"，因为契约已经从"补偿写"上移到"事务" |
| N5 | admit 失败有补偿，补偿失败不顶掉原始错误 | `test_jobs.py::test_a_cancel_landing_midway_is_not_written_back_to_queued`、`test_a_failing_closing_write_does_not_replace_the_real_error`（均改写） | 前者断行停在 `canceled`（守卫在 `new` 才会这样；无守卫的补偿会把它写成 failed）；后者让写入抛 "snapshot write refused"、让补偿抛 "database is locked"，断提交方读到的仍是**前一句**——这一条此前失败过两次：第一版把 `transition_job` 整体改成抛错，结果 `queue.admit` 自己先炸（它也调 `transition_job`），改成"上膛"标志仍不对，最后换成不依赖 cancel 的两条独立消息才真正只测补偿 |
| N6 | 报表与详情不带端点凭据 | `test_reports.py::test_a_forwardable_report_drops_the_endpoints_credential`（新） | 把 job 行改成 `http://agent:<secret>@eval.example.com/rpc?key=<secret>&v=2`（合法输入，`AcpEndpoint.http` 只看 scheme），断详情与 `results.environment` 都是 `http://eval.example.com/rpc`、两份 payload 的 JSON 文本里没有密文，再**读回落盘的 md 与 json 两个文件**确认渲染产物也没有——只断 payload 区分不了"渲染时脱敏"和"事后字符串替换" |
| N7 | 队列视图（含 `GET /v1/jobs` 全量列表）不带端点凭据 | `test_jobs.py::test_the_queue_views_drop_the_endpoints_credential`（新） | 同时断库行里密文出现两次（runner 还要用它重连）与两个读视图都脱敏；这条是自查项，起因是把 `_job_item` 误判成"提交方看自己那一行"，而它同时服务需求 5 的全量列表 |

计数：`test_cli.py` 由 17 项增至 19、`test_jobs.py` 36 项（其中 3 项改写、1 项新增）、`test_store.py` 23 项、`test_datasets_api.py` 31 项、`test_reports.py` 33 项。全量 **523 passed, 1 warning in 15.06s**（`pytest tests/cpd/acp_remote_eval -q`，命令与环境同 §4.1；文档改完后收口重跑 **523 passed in 15.16s**，代码未变）。反向验证做了一次实测：把 `cli.py` 落盘文件名的 `.name` 守卫改回原文，`test_a_service_that_names_a_path_for_its_file_does_not_choose_where_it_lands` 立即失败（0.34 s），恢复后全绿。

H3 合并边界重跑：`git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` **仍为空输出**；本批新增文件只有 `pawbench/cpd/acp_remote_eval/redact.py`（28 行，脱敏规则的单一真源）与 `pal_sdd/feat_acp_remote_eval/` 下的文档，特性文件数因此 **51 → 52**（后端 28→29：26 个 .py + `requirements.txt` + `README.md` + `service/config.example.yaml`；测试仍 23 个 .py）。行宽普查：49 行／16 文件，与第三轮一致，本批新增代码 0 超宽（`redact.py`、`api.py`、`datasets.py`、`jobs.py`、`reports.py`、`cli.py`、`store.py` 全部干净）。

### 4.13 M2 第六批：K2／F2 的泄露扫描（`tools/scan_shared_leakage.py`）

判据 9（K2）与 F2 在 §2 里挂了很久的"待执行"，原因是它们的判据写成了**人工 grep**——"把 `shared` 档响应导出、逐条搜敏感字段"。人工检查有两个毛病：只在有人真去 grep 的那一天有效，以及词表只存在于那条判据的文字里，改字段的人不知道自己在改它。这一批把它换成一份可运行的规则：`tests/cpd/acp_remote_eval/tools/scan_shared_leakage.py`，同一个模块既能被用例 import，也能被人拿去扫一份抓下来的响应再转发。

词表分三份，只有这一处定义：

| 词表 | 内容 | 它防的是哪一种走偏 |
|---|---|---|
| `GRADING_SIDE_FIELDS` | `rubric_excerpt`、`expected_behavior`、`judge_notes`、`judge_served_models`、`workspace_path`、`transcript_path`、`downloads` | 裁剪点位放错：这些字段只由判分侧产生，出现在交给排行榜的 `results` 里说明裁剪点错了（原名叫 `SHARED_ONLY_FIELDS`，`shared` 档撤掉后改名） |
| `ANSWER_KEY_FIELDS` | `automated_checks`、`llm_judge_rubric`、`grading_criteria`、`grading_code`、`checker_source`、`judge_prompt` | 答案外泄：任何档都不该有。`judge_prompt` 现在还不存在，写进表里正是为了"字段还不存在时列表就不被检查"这一刻 |
| 三组形态正则 | heading（**只认两种形状**：标题点名判分小节 `rubric excerpt`／`expected behavior`／`answer key`…，或标题本身就是小节名 `## Rubric`）、label（`rubric_excerpt:`／`= `）、tag（`<judge_prompt`） | 换了键名不改正文：payload 精简了，渲染层照旧把 rubric 排成一个标题——`md`／`html` 没有 JSON 结构可走，只能按文本扫。第二行是第五轮加的：先前那一版按"标题里出现 rubric"判，实测会命中 `# How to write a rubric`，而任务 prompt 会原样进 shared 报表与 manifest——喊一次狼，下一个人就把这次扫描 `--profile` 掉了 |

扫描档就两个：`forwardable`（要交出去的文档：`results` payload、`md`／`html` 报表、交给 agent 的 manifest，禁上面两份）与 `internal`（自己看的：`json` 详情与报告，仍禁答案表）。命令行开关是 `--profile`（早期叫 `--tier`）。`banned_fields()` 对未知档位抛 `ValueError`——写错档位名不能默认成更宽的那一档。

发现项的形状是**位置而不是内容**：`field <名> (line N)`、`key <名> (at tasks[0].rubric_excerpt)`、`marker <型> (line N)`，绝不带被匹配的片段。理由和词表同源：片段可能就是 rubric 原文，而这段输出会被贴进 CI 控制台（`logging-quality` 第 3 条）。落盘的 `.json` 按**文件自己的字节**算行号，不按重新序列化后的 body 算——一行压缩过的捕获文件报"line 4"是在骗人（这一条是命令行实测时自己撞见的，见 §4.14）。

四条用例（`test_reports.py` 33→36、`test_exchange.py` 55→56）：

| 用例 | 断的 | 为什么它不算自证 |
|---|---|---|
| `test_the_rendered_documents_pass_the_leakage_scan` | 九份文档一次过：`shared` detail、`results`、`full` detail 三份 payload（后者按 `internal` 档）＋ `md`·`html`·`json` × `shared`·`full` 六份**落盘文件正文**；后段植入 `{"tasks": [{"rubric_excerpt": …}]}` 与 `"## Expected behavior"`，并钉 `## How to write a rubric for the essay` → `[]` | 植入项断 `key rubric_excerpt (at tasks[0].rubric_excerpt)` 与 `marker heading (line 1)`，所以前半段的"零发现"不是规则空转。渲染文件从 `exchange.report_path()` 读回，不是把 payload 重新序列化一遍。**两半证的不是一件事**：干净半区是生产检查，植入半区只保证扫描器自己还会响 |
| `test_a_scan_that_never_ran_does_not_report_a_clean_bill` | `main()` 的三个退出码各钉一次：打错路径 → 2、空目录 → 2、干净目录 → 0、植入后同一目录 → 1；顺带 `scan_file()` 对一行压缩的 `detail.json` 断 `["field rubric_excerpt (line 1)", "key … (at tasks[0].rubric_excerpt)"]` | 这一条是第五轮那处**严重**项的反证：修之前同样的命令打印 `0 finding(s)` 并以 0 出门。同时断 stderr 里有字段名而**没有**植入值（`"tone" not in captured.err`），把"位置不带内容"钉成契约 |
| `test_the_rubric_text_reaches_the_document_and_the_export` | 答案**文本**跟着走一遍：详情与落盘 json 里有 `Award 1.0 when the reply is polite.`，落盘 md 里连 `polite` 都没有，且 md 过 `forwardable` 扫描（`shared` 档撤掉后，由这条接替原来「两档各扫一遍」的覆盖面） | 键位断言在 `rubric_excerpt: None` 上也会过，而本文件此前的 fixture **一道题都没有 rubric**（`write_task` 不写 `## LLM Judge Rubric`，除 `mail_b` 外全是 checker 判分）——用例名叫 "hides the rubric"，桌上一条 rubric 都没有。`support.write_task` 因此新增 `rubric=` |
| `test_a_manifest_carries_nothing_from_the_grading_side` | `build_manifest()` 的 payload 按 `forwardable` 扫为零，且 `task.expected_behavior`／`task.llm_judge_rubric` 两句原文都不在 `json.dumps(manifest)` 里 | manifest 是本特性唯一**从 prompt 而不是端点**离开的文档，响应体上的断言永远碰不到它；`FakeTask` 因此补上这两个字段——没有 rubric 的任务证不了"构建时没带 rubric" |

命令行实测（`<venv>/bin/python tests/cpd/acp_remote_eval/tools/scan_shared_leakage.py <目标>`，三个临时文档：一份干净的 `report.md`、一份 `## Expected behavior` 开头的 `detail.md`、一份压缩成一行的 `detail.json`）：

```bash
$ ... scan_shared_leakage.py out/report.md
1 document(s) scanned as forwardable, 0 finding(s).                     # exit=0
$ ... scan_shared_leakage.py out/
out/detail.json: field rubric_excerpt (line 1)
out/detail.json: key rubric_excerpt (at tasks[0].rubric_excerpt)
out/detail.md: marker heading (line 1)
3 document(s) scanned as forwardable, 3 finding(s).                     # exit=1
$ ... scan_shared_leakage.py --profile internal out/detail.json
1 document(s) scanned as internal, 0 finding(s).                        # exit=0（同一文件按 forwardable 扫是 2 finding）
$ ... scan_shared_leakage.py nope
nothing was scanned: no such path: /tmp/leak_smoke/nope                 # exit=2
```

判据四条：只说"某任务让你写一份评分标准"的干净文档**不报**；发现进 stderr、统计行进 stdout；退出码 **0=扫过且干净／1=有发现／2=没扫**（2 覆盖三种：路径不存在、目录下没有可扫文档、文档数超 `MAX_DOCUMENTS=500`）；`.json` 解析失败（截断下载）退回按文本扫而不是跳过，超过 `MAX_DOCUMENT_BYTES=8 MiB` 记一条 `not scanned: …` **finding** 而不是静默放行。

计数与边界：本批落地时全量 **525 passed**，第五轮修复后收口 **529 passed, 1 warning**（15.41s；P6 那条 `assert`→`raise` 落地后又重跑一次确认同一数，15.05s）。H3 重跑 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` **仍为空输出**。特性文件数 **52 → 53**（后端 `pawbench/cpd/**` 仍 29，测试 23 → 24 个 .py，新增的是 `tests/cpd/acp_remote_eval/tools/scan_shared_leakage.py`，送检时 192 行、第五轮修完 290 行）。

### 4.14 M2 第七批：第五轮检视的 18 项发现修掉 12 项，与 L16 关闭

检视记录见 `review_acp_remote_eval.md` 第五轮（1 严重 / 12 一般 / 5 建议）。这一批没有新功能，全部是**把检视者的判据变成断言**，加 4 条用例（525→529：退出码契约、rubric 文本双向、`runtime` 与 `daemon` 的循环探活各一条）。

| # | 修复 | 用例／证据 |
|---|---|---|
| P3 严重 | 没扫 = exit 2，不再冒充干净 | `test_a_scan_that_never_ran_does_not_report_a_clean_bill`（§4.13 第二条） |
| P8 | 发现只带位置不带内容 | 同一用例断 `"tone" not in captured.err`；`field/key/marker (line N \| at path)` 三种形状由 §4.13 的三条断言分别钉住 |
| P10 | heading 不再命中题面里的 "write a rubric" | `assert rules.find_in_text("## How to write a rubric for the essay\n") == []` |
| A2/A3 | `.jsonl` 进后缀集；`full` 档三份文件按 `internal` 扫 | K2 用例的 2 档位 × 3 格式矩阵 |
| P1/P4 | 体积与条数上限、不可读文件 | `MAX_DOCUMENT_BYTES` → `not scanned: …` finding；`except OSError` → `unreadable: <类型名>`（不带异常文案，它可能含绝对路径）；`MAX_DOCUMENTS` → exit 2 |
| P14/P15/P16 | 三条"名不符实"的测试断言 | K2 用例 docstring 重写为"两半各证什么"；md／html 的判别力限制写进 docstring 而不是删用例；`write_task(rubric=)` + 新的文本级用例 |
| P6 | `support.py` 的 `assert` 改显式 `raise` | — |

**L16（第三轮登记、本轮关闭）**：M8 那两处 `asyncio.to_thread` 此前没有鉴别性用例——单线程用例看不出一次同步 SQLite 调用有没有占住事件循环。两条新用例的做法是**让被阻塞的那次调用等一个只有另一个协程能置位的 `threading.Event`**：`test_runtime.py::test_a_store_query_hanging_does_not_hang_the_event_loop`（拆 `runtime.py:328` → 2.50 s 判负）、`test_daemon.py::test_a_startup_reconcile_hanging_does_not_hang_the_event_loop`（拆 `daemon.py:192` → 2.36 s 判负）。判负而不是挂死是关键：探活协程拿不到执行机会就在 2 s 超时处返回 False，`released` 由它置位。daemon 那条还顺带断"离开事件循环不等于跳过工作"——端口打开时孤儿 job 已经结算成 `failed(recovered)`。

反向验证实测三次（跑完即恢复，`git hash-object` 比对确认字节一致）：`reports.py:399` 的档位守卫改恒真 → 3 条用例红（K2 里变红的是 `json report @ shared`，md／html 仍 0 条——检视者 P14 判对，已如实写进 docstring）；两处 `to_thread` 各拆一次 → 对应探活用例各判负。

行宽与文件数：本批新增代码 0 超宽，仍是 **49 行／16 文件**；文件数仍 **53**（改的都是已有文件）。


行宽普查这一批换成了可复现的定义，之前记的数字用的instrument不对：`pyproject.toml:11` 是 `line-length = 100`（字符），而 `[tool.ruff.lint]` 里 `ignore = ["E501"]`，所以它不是 lint 项、只能自己数。**计数口径 = 字符数 > 100**，用 `python - <<'PY'` 遍历 `pawbench/cpd` 与 `tests/cpd/acp_remote_eval` 下非 `__pycache__` 的 .py。当前 **49 行／16 文件**（后端 17 行／7 文件、测试 32 行／9 文件），与本批之前一致：`scan_shared_leakage.py` 最长 97 字符、两条新用例与 `support.py` 的改动均无超宽。顺带记下这个坑：`awk 'length>99'` 数的是**字节**，而 `# ── leases ──…` 这类分隔行是 80 字符／约 200 字节，用 awk 会把 49 行误报成 79 行——L10 的计数以前就是这么漂的。

### 4.15 M2 第八批：出口批关闭 L17／L19／L21（+18 条判别性用例）

这一批没有新功能，做的是一件此前一直没空做的事：**把已经登记为遗留的三条"能跑但没人兜底"补平，并给每条修复配一条"删掉修复就会红"的用例**。529 → **547 passed, 1 warning in 15.91s**，+18 按遗留分三组（下表 L19 9 条、L21 7 条、L17 2 条），收口时的收集数是 `test_datasets_api.py` **37**、`test_reports.py` **39**、`test_jobs.py` **38**、`test_datasets.py` **35**、`test_pilot.py` **19**、`test_control_api.py` **40**。

| 遗留 | 修的是什么 | 钉住它的用例 | 反向实测 |
|---|---|---|---|
| **L19** | 四条把调用方输入问题升格成 500 或假告警：畸形 zip（method 99／成员名冲突／目录名 `*.md`）抛非 DomainError；transcript 只兜 `FileNotFoundError` 且一行坏则整页 500；`unknown_filter_key` 一类未入表的码反过来打 `logger.error("unmapped code")`；pilot 在数据集已存在时完全跳过构成校验 | 9 条（`test_an_archive_this_build_cannot_decode_is_a_refusal_not_a_crash`、`test_two_members_wanting_one_spot_say_which_one_lost`、`test_a_damaged_transcript_costs_a_count_and_not_the_page`、`test_a_damaged_line_is_stepped_over_and_not_reread`、`test_a_transcript_the_service_cannot_open_says_which_of_the_two_it_is`、`test_a_filter_key_nobody_spelled_right_is_not_an_alarm`、`test_every_control_plane_code_promises_a_status`、`test_a_pilot_that_stopped_covering_says_so_at_every_start`、`test_the_gate_is_the_number_the_seed_advertises`） | **9/9 判红** |
| **L21** | 变更类操作只记对象 id 不记操作人；`package_unsafe_path` 的安全告警不记肇事成员；`cancel` 把 `stop_running(job_id)` 写在 `logger.info(extra=...)` 的实参里——副作用挂在日志上，它抛错会把已经成功的取消变成 5xx | 7 条用例，由 5 处变异分别覆盖（`test_an_admins_recut_is_logged_as_the_admin`、`test_a_deleted_dataset_names_the_operator_and_the_author`、`test_a_package_guard_refusal_says_who_sent_what`、`test_the_cancel_logs_which_half_of_it_actually_happened`、`test_a_cancel_that_reached_nothing_is_loud_enough_to_be_seen`） | **5/5 判红** |
| **L17** | 上传只有体积闸、没有并发闸：默认线程池 ~32 个上传同时各占一份 ≤256 MB 临时文件，先填满的是磁盘而不是配额 | `test_two_packages_land_and_a_third_waits_its_turn`（三条并发上传全 201，峰值同时落盘数 = 2）、`test_a_disk_without_room_is_said_before_the_package_arrives`（507 `package_disk_full` 在字节到达之前）、同一条用例另证 `package_disk_full` 属守卫码所以进告警 | **3/3 判红** |

**反向验证脚手架在这一批里被硬编码成契约**（`/tmp/reverse_l19.py`、`reverse_l21.py`、`reverse_l17.py`），起因是一个自己的坑：Python 的 `.pyc` 按 **mtime（秒级）+ 文件大小** 判新鲜，所以"把一段代码改成等长"的变异会让子进程读到**旧字节码**，判出一个假的"这条用例不判别"。三份脚本现在都做四件事：

1. 跑之前清 `pawbench/cpd/**/__pycache__` 与 `tests/cpd/**/__pycache__`，并在子进程环境里置 `PYTHONDONTWRITEBYTECODE=1`；
2. **BASELINE 预跑**：不变异时这些用例必须全绿，否则整个脚本 `ABORT` 退出——反向验证的结论只有建立在"用例本来就是绿的"之上；
3. 变异写入前记下原文 sha256，`finally` 里恢复并比对，不一致直接抛；
4. 结尾打印**幸存者清单**（拿掉修复仍然转绿的用例 = 这条用例什么都没钉住）而不是"通过"，并以退出码区分。

顺带记下收集数与 `def test_` 计数不是一回事：参数化让 `test_pilot.py` 14 个 def 收集成 19 条、`test_datasets_api.py` 35→37。本文件一律按 `--collect-only` 的收集数记。

### 4.16 M2 第九批：第六轮检视的 8 项发现（+8 条，547→555）

第六轮检的是第八批那份 diff（`review_acp_remote_eval.md` 第六轮，1 严重 / 6 一般 / 1 建议）。**547 → 555 passed, 1 warning in 15.98s**：`test_datasets.py` 35→37、`test_reports.py` 39→41、`test_datasets_api.py` 37→39、`test_control_api.py` 40→42。

| # | 发现 | 处理与钉住它的用例 | 反向实测 |
|---|---|---|---|
| 1 **严重** | `_copy_package` 先 `rmtree`+替换目标目录，之后的 `ensure_category` 仍可拒绝 → 检视者在 scratch store 上实测：DB 行 `task_ids=['cust_a']` 指向的文件已被换成 `cust_b.md`；换新 id 则留下没有 DB 行的孤儿目录 | 已修：还会抛的校验（takeover、分类名）全部提到落盘之前，新增 `_category_name_or_refuse` 静态方法让"解析名"与"拒绝"是同一个答案的两种用法。`test_a_refused_category_leaves_the_stored_package_and_its_row_alone`、`test_a_refused_category_does_not_leave_a_package_directory_without_a_row` | 把名称判定挪回 copy 之后 → **2 条同时判红** |
| 2 | 剩余空间只测 `tempfile.gettempdir()` 所在卷，而真正落盘处是 `datasets.custom_dir`（`/tmp` 是 tmpfs 时这 256 MB 直接吃内存），docstring 却写着保护"DB/转录/报告共用的卷" | 已修（测哪卷说哪卷）：两卷各查一次，缺在的包目录用 `_existing_parent` 退到最近的真实目录；`test_a_full_package_volume_is_refused_though_the_temp_directory_is_empty` 断**两只 `disk_usage` 调用分别落在临时卷与包卷**、告警文案点的是包卷 | 只测临时目录那一卷 → **判红** |
| 3 | `_json_object` 用 `request.body()`，**无任何大小上限**；artifact PUT 不占闸、不查空间 | 已修 JSON 那一半：`MAX_JSON_BODY_BYTES = 1 MiB`，`_json_object` 改走带上限的 `_read_body`（新码 `body_too_large` → 413，已入 `_CONTROL_STATUS`，所以 `test_every_control_plane_code_promises_a_status` 一并盯住它）。`test_a_control_body_is_read_up_to_a_ceiling_and_not_as_far_as_the_caller_sends`、`test_json_nested_past_the_recursion_limit_is_the_callers_error_not_ours` | 上限取掉 → 判红；`except (ValueError, RecursionError)` 改回只捕 `ValueError` → 判红 |
| 4 | `report?format=zip` 在 `io.BytesIO` 里拼整包再 `getvalue()`（两份全量内存），大小由已存产物决定、不受包体积闸约束；`_write` 失败时 `.{name}.part` 不删 | **不修**，整条并入 L20（那行本来就登记了 `.part` 唯一名 + 失败 unlink 与报告文件保留策略）；闸的覆盖面那一半并入 L30 | — |
| 5 | `_read_window` 只把 `open()` 的 `OSError` 归为 `unreadable`，迭代中途的 `OSError` 冒到没有 handler 的路由 → 500 | 已修：整个走档循环包进 `except OSError` → `unreadable`。`test_a_transcript_that_fails_mid_read_is_unreadable_and_not_a_half_page`（`monkeypatch` 换掉 `Path.open`，只对 `transcript.jsonl` 递出一个读到第二行就抛的文件对象） | 守卫拆成恒真/恒假 → **判红** |
| 6 | `_timeline_events` 只捕 `ValueError`，而超深嵌套行抛的是 `RecursionError`（已验证非其子类）→ 一行坏数据把整页打成 500 | 已修：一并计入 `damaged`。`test_a_line_that_is_too_deep_to_parse_costs_a_count_and_not_the_page` 用 `b"[" * 50000`——**这个数是量出来的**：5000 层能解析、20000 层抛，取远高于抛侧的数才不随解释器 recursion limit 漂移 | 见 #3 第二行（同一对捕获） |
| 7 | 闸圈的是协程不是线程：`to_thread` 不可取消，客户端断连时 `async with` 先释放许可、解包线程仍在写 staging；全路径无超时 | **不修**，登记 L29——它要的是"许可随线程结束才释放"或闸内 `asyncio.timeout` 的取舍，不是补一条断言 | — |
| 8 建议 | `test_two_packages…` 的峰值取自服务调用，看不到流式阶段（把 `async with` 缩到只包解包仍全绿）；`peak == MAX_CONCURRENT_PACKAGE_UPLOADS` 是常量自比（2 改成 32 也绿）；`volumes == [Path(tempfile.gettempdir())]` 把"测错卷"钉成期望；两个异常 handler 同名 `_refuse`；三处函数内 `import` 无"为什么"注释 | **全部已处理**：计数器改为包住 `api_module._stream_body_to_file`（运行期经模块属性查找才换得动），峰值同时断 `== 常量` 与 `< 3`（绝对上界，改常量为 32 会红）；`volumes` 断言改成"两只卷分别是临时卷与包卷"；两个 handler 改名 `_refuse_exchange`／`_refuse_service`；`hashlib`／`json`／`shutil` 提到模块级（都是 stdlib，不存在"避免循环依赖"这个理由） | #1/#2/#3/#5 的红都来自这些改过的断言本身 |

**这一批最值得留下的两条**：① 严重项 #1 是检视者**自己起进程复现**的（报告里写了实测的 DB 行与文件名），不是我从代码里认出来的——而它已经在第八批的 547 项全绿里跑了一整轮，说明"覆盖了这条路由"和"钉住了这条路由的失败顺序"是两件事；② #8 的三条全是**断言看着错的步骤**：并发闸的峰值取自解包调用，于是这一批把闸往里挪一格都不会红。反向验证脚本现在专门有"改位置而不是改有无"的变异（`/tmp/reverse_round6.py` 的第 1、2、4 条），第八批那三份脚本证不了这一类。

反向验证实测（`/tmp/reverse_round6.py` 八条 + `/tmp/reverse_l17.py` 三条，BASELINE 全绿后逐条变异、`finally` 恢复并比对 sha256）：**11/11 判红，零幸存者**。`reverse_l17.py` 本轮重跑过一次：它原来的 `ROOM_FIX`/`GATE_FIX` 锚点已被 #2 的两卷改写顶掉，脚本会打印 `SKIP` 并把跳过算进幸存者——**锚点失效不会静默，但也不会自己修好**，所以两份脚本现在都在文档里点名，改代码的人要顺手改锚点。

收口重跑：全量 **555 passed, 1 warning in 15.98s**；H3 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 过滤掉 `cpd/` 后**仍为空输出**；超宽普查（口径见 §4.13 末段）仍 **49 行／16 文件**，本批新增 0 行（`api.py` 最长 100 字符，正好在 `line-length = 100` 的上界内）；`.py` 文件数 **50**（后端 26／测试 24，口径 `find pawbench/cpd tests/cpd -name '*.py' -not -path '*__pycache__*'`——此前几批记的 53/29 是另一条命令的产物，以本行这条为准）。

### 4.17 M2 第十批：关闭 L18（热路径上的四类重复全量工作，+5 条，555→560）

第四轮登记的 L18 是四类同一形状的工作：看板每轮询一次，就把已经算过的东西再算一遍。修法都不是"加缓存"这一句，而是四处各自的那一条判别性用例——**断的是次数，不是耗时**，因为这类回归快得测不出来，慢得没人承认。

**555 → 560 passed, 1 warning in 16.10s**：`test_datasets.py` 37→**41**、`test_reports.py` 41→**42**。后端改动 3 个文件（`service/store.py`、`service/datasets.py`、`service/reports.py`）、零新增文件。

| # | 位置（登记时的行号已漂，按代码定位） | 原来每次 poll 付的钱 | 修法 | 钉住它的用例 | 反向实测 |
|---|---|---|---|---|---|
| ① | `datasets.list_categories` → `store.datasets_with_category` | 每个分类一次 `SELECT categories FROM datasets` + 一次 JSON 解码（N+1） | 新增 `store.category_dataset_counts()`：一趟扫完全表、`datasets_with_category` 退化成它的一次查表 | `test_category_counts_read_the_catalogue_once_not_once_per_category`（4 个分类，断 `FROM datasets` 只读 1 次，同时断四个 count 仍各是 1） | 把 count 改回逐分类调用 → **判红**（4 次读） |
| ② | `reports._task_entry` 在任务循环里 `list_artifacts(job_id, task_id=…)` | 每个任务一次 `artifacts` 查询；详情文档与 zip 两条路都是这个形状 | 新增模块级 `_artifacts_by_task(store, job_id)`：一次查全 job、按 `task_id` 分桶；`_task_entry` 改为接收自己那一片（`recorded`） | `test_job_detail_reads_the_artifact_rows_once_for_a_whole_job`（3 任务、2 产物：文档阶段断"只有一次、且 `task_id is None`"，zip 阶段断**增量**恰好两次；同时断三个任务的 `artifacts`／`downloads` 一片没少） | 文档那半退回逐任务查询 → 判红；只把 zip 那半退回（`_zip` 里换成按任务查的懒壳）→ **也判红** |
| ③ | `datasets._index`：custom 数据集每次 `describe` 重解析包里全部 md | 每次 poll 每行数据集解析整个包 | 按任务文件签名（`(name, st_size, st_mtime_ns)`）缓存解析结果，`MAX_INDEX_CACHE = 32` 封顶、满了先淘汰最早写入的那条 | `test_a_package_is_parsed_once_until_one_of_its_files_changes`（两次 `describe` 只解析 1 次；改写包内一个 md 后**必须再解析一次**）+ `test_the_index_cache_does_not_grow_with_the_catalogue`（33 个数据集后 `_indexes ≤ 32`，被淘汰那个再 `describe` 仍对） | 缓存整个不查（`cached = None`）→ 判红；**只去掉签名比较**（永远复用）→ 判红，红的是第二半 |
| ④ | `datasets.tasks_for_run` 走 `load_all_tasks()` 再筛 | 选中 2 个任务也要解析整个语料目录；`reports._bodies` 每 job 每数据集调一次 | 改为按 `record["task_ids"]` 从索引取路径、逐个 `load_task`；一个 `TaskLoader` 实例循环（不是每任务一个，否则核心那行 `TaskLoader initialised` 就进了热路径） | `test_tasks_for_run_reads_only_the_tasks_the_dataset_selected`（`datasets_module.TaskLoader` 换成 `load_all_tasks` 直接抛的 subclass，仍要返回选中的两个） | 退回全量走目录 → **判红**（抛的 `AssertionError` 就是断言本身） |

**这一批要留下的三条判断**：① **缓存的另一半是失效**——第四轮的登记语是"热路径重复全量工作"，但只删缓存会红、只删失效检查也红才算把这条修完，所以 ③ 用了两条变异去打同一个用例（`reverse_round7.py` 的第 2、3 条），后者红的位置是"改了文件仍读旧索引"那一句，不是"解析了两次"那一句；② 失效判据是**目录列表 + 三个数字**，不是内容 hash——哈希内容正是这次想省掉的那次读，代价写在 `_task_file_signature` 的 docstring 里；③ 淘汰策略是**按写入顺序 FIFO，不是 LRU**：命中不重排，所以最坏情况是"每次 poll 都淘汰正在用的那条"只在数据集数刚好越过 32 时出现，此时付的仍是本批修之前每一次 poll 都要付的解析，不是新成本。**没测的一面**：FIFO 的"淘汰哪一条"没有用例钉（钉它等于把策略写死），`_indexes` 的长度是被 `MAX_INDEX_CACHE` 一个常量管的，改这个常量只需同步改 ③ 的第一行断言。

反向验证实测（`/tmp/reverse_round7.py`，BASELINE 5 passed → 逐条变异、`finally` 恢复并比对 sha256）：**7/7 判红，零幸存者**，其中两条改的是"缓存的失效半边"和"zip 那半边读了同一个 helper"——都是原批次的修复在位、但只装了一半的形状。脚本这次支持一条变异含多处替换（② 的两处：删调用行 + 改调用点），锚点全部取自本批落地后的原文。

收口重跑：全量 **560 passed, 1 warning in 16.10s**；H3 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 过滤掉 `cpd/` 后**仍为空输出**；超宽普查（口径见 §4.13 末段）仍 **49 行／16 文件**，本批新增 0 行；`.py` 文件数仍 **50**（后端 26／测试 24，口径 `find pawbench/cpd tests/cpd -name '*.py' -not -path '*__pycache__*'`）。一处**行为改动如实登记**：`tasks_for_run` 的返回顺序从"目录 glob 序"变成 `record["task_ids"]` 序（存的是 sorted 快照，所以实际是把语料目录序换成了 id 字典序）；查过两个消费方（`runner` 按 task_id 派发、`reports._bodies` 建的是 dict）都不依赖顺序，④ 的断言写的就是排序后的两个 id。

### 4.18 M2 第十一批：第七轮检视的 6 项发现（+3 条，560→563）

第七轮检的是第十批那份 diff（`review_acp_remote_eval.md` 第七轮，1 严重 / 3 一般 / 2 建议）。**560 → 563 passed, 1 warning in 16.03s**（三条全在 `test_datasets.py`，41→44）。

| # | 发现 | 处理与钉住它的用例 | 反向实测 |
|---|---|---|---|
| 1 **严重** | `_indexes` 的「判满→挑最旧→pop→写」四步没串行化：路由全走 `asyncio.to_thread`，两线程对同一 key 各 pop 一次，第二个抛 `KeyError`。检视者 1800 次并发 describe 实测 6 次；看板侧是 500，**报表侧被 `reports.py:485` 的宽 `except Exception` 降级成静默丢字段** | 已修：解析留在锁外，命中判定与「写回 + 淘汰」各进 `threading.Lock`（`datasets.py:264/819/826`）。用例 `test_two_workers_reaching_a_full_cache_do_not_evict_the_same_key`——测试侧把 `_indexes` 换成 `pop` 先睡 0.05 s 再转真 `pop` 的 dict 子类，两个线程各 describe 一条未缓存的数据集；**睡在测试里不睡在服务里**，否则这条竞态就是线程运气 | 整体拆锁、**只锁读半边**（写回仍在锁外）两条变异各判红，实测失败信息 `KeyError('ds_0')`；检视者的 `probe_race7.py` 重跑 → 1800 次 `errors=none` |
| 2 | `BuiltinCatalog._tasks` 永不过期；内置语料缺文件时 `is_file()` 静默跳过 | **不修** → L32（要给 builtin 一支加签名，等于承诺"语料可在进程存活期更换"，而 M4 打标才会真改它；还要先定"改名算删除还是新增"） | — |
| 3 | 一次 md/html 渲染 = 2 遍全量 `_bodies` + 3 次 `list_job_tasks`（detail 路线是 1/1） | **不修** → L33（改法是 `results()` 接受已算好的 rows/bodies，属接口形状变更，不混进关遗留批）；本轮重跑探针确认数字未变 | — |
| 4 | 一行 `categories` 里重复同名分类被重复计数：`{categories:["Office Tooling","office tooling"]}` 实测 `dataset_count=2`，看板数字与 `delete_category` 的引用数是同一个错数字 | 已修**两半**：读侧每行 `dict.fromkeys(...)`（`store.py:641`），写侧存库前去重（`datasets.py:297` 与 `396`，后者仍在 `_copy_package` 之前，不动第六轮严重项定下的顺序）。用例 `test_a_category_filed_on_one_dataset_twice_is_one_dataset`：先走公开创建路径断存下的就是 `["field kit"]`，**再直接落一条旧格式的重复行**断计数与拒绝数字——已经入库的行不会被重写，所以读侧必须自己判对 | 读侧、写侧各一条变异分别判红；探针重跑 → `{'office tooling': 1}`、存库列 `['office tooling']` |
| 5 建议 | `tasks_for_run` 的 `load_task` 直抛，旧 `load_all_tasks()` 对单文件异常是跳过——索引与磁盘不一致时 runner 从"少一个任务"变成整单失败 | 已修：单文件 `try/except ValueError` + `logger.warning` 带 `dataset_id`／`task_id`／`reason`。**这条是第十批自己引入且当时未登记的行为变更**，所以按修处理。用例 `test_an_unparseable_task_file_costs_its_task_and_not_the_run`：先 `describe` 烘热索引，再换上一个只对 `cust_b` 抛 `ValueError` 的 loader——不这么做，`load_all_tasks` 自己就把坏文件跳过了，被测的那一步根本不会发生 | 改回直抛 → 判红（返回值与日志两句一起红） |
| 6 建议 | zip 在 `BytesIO` 里两份全量 + `.part` 失败残留 | 不重复登记：已在 **L20**（保留策略）与 **L30**（闸与内存上界） | — |

**这一批最值得留下的两条**：① 严重项 #1 又一次不是从代码里认出来的——五条用例与七条变异**都覆盖了这条路由**，但没有一条在两个线程里跑过，于是"这条缓存正确"与"这条缓存在并发下正确"是两件事，而前者全绿；同一条发现还带出第二层的坏：`reports.py:485` 的宽 `except Exception` 会把 500 变成静默缺字段，**检视者把它叫作数据错误**。这条本批未动（不在第七轮发现清单里，改它要先定"报表侧吞异常收到哪几类"），已登记 **L34**；② #5 的用例形状说明"先烘热索引再换 loader"为什么必要：`_load_task_summaries` 与 `tasks_for_run` 用的是同一个 `TaskLoader` 类、运行期经模块属性查找，补丁会同时命中两处——**测试要的不是"有个文件坏了"，而是"索引认为它没坏"**。

反向验证实测：`/tmp/reverse_round8.py` 五条变异（BASELINE 3 passed）→ **5/5 判红、零幸存者**，其中"只锁读半边"是本轮新增的变异类型（证的不是有没有锁，而是锁在起作用的哪一步）。锚点维护如实记录：`_index` 与 `tasks_for_run` 的文本被本批改写后，`/tmp/reverse_round7.py` 四条（`CACHE_ON`／`SIGNATURE_CHECK`／`CACHE_BOUND`／`SUBSET_READ`）与 `/tmp/reverse_round6.py` 一条（`NAMES_BEFORE_COPY`）已同步修正，三份脚本各重跑一遍 → **7/7、8/8 全判红、零幸存者**，`finally` 恢复后逐文件 sha256 与原文件一致。

收口重跑：全量 **563 passed, 1 warning in 16.03s**；H3 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 过滤掉 `cpd/` 后**仍为空输出**；超宽普查（口径见 §4.13 末段）仍 **49 行／16 文件**，本批新增 0 行（最长的新增行 91 字符）；`.py` 文件数仍 **50**（后端 26／测试 24）。改动文件三个：`datasets.py`（锁 + 两处存库去重 + 单文件容错）、`store.py`（读侧去重）、`test_datasets.py`（+3 条），无新增文件。

**证据归档（本节的 `/tmp` 路径现在有了常驻副本）**：`test_` §4.15–§4.18 与 `review_` 第五~七轮里每一条"删掉修复就会红"的数字，原先只存在于 `/tmp/reverse_round*.py` 与 `/tmp/probe_*.py`——**这些脚本是判据的一部分，但重启即失**，于是"证据可复现"只在当天成立。现已逐字节复制到 `reverse_checks/`（6 份脚本 + 一份 README，全在文档目录下，代码侧文件数不变），README 写清三件下一个人一定会踩的事：变异脚本会就地改源码、**不能与任何读者并行**（探针只读不受限）；锚点与它盯的代码是同一份要维护的资产，`SKIP` 计幸存者而不是算通过；BASELINE 不绿就中止。脚本顶部 `REPO` 是机器绝对路径，换机器改那一行即可——保留绝对路径而没改成 `__file__` 推导，是为了让归档副本与产出这些数字的那次运行逐字节一致（`cmp` 六份全 identical）。**同一原因也让这些副本里的 9 条超宽行（4 个文件）没有折行**：它们在普查口径之外（口径只覆盖 `pawbench/cpd` 与 `tests/cpd/acp_remote_eval`，所以 49 行／16 文件的数字不受影响），但如果哪天把普查扩到 `pal_sdd`，要清楚这里不是漏网而是**故意保持与运行过的那份一致**——重排一份证据脚本，就等于让它不再是那次的证据。

### 4.19 真语料上的 pilot 种子实测（不改代码，第八轮等待期间）

§1 pilot 那一行从第三批起就写着"**已建**"，而 `test_pilot.py` 的 19 项全部跑在 `support.write_task` 造出来的合成目录上——**门槛管的是这 15 个 id，语料里到底有没有这 15 个 id，此前没有任何一条绿过**。本次用真实 `data/pawbench-v1.0`（`tasks/` 下 150 个任务文件、全目录 321 个 `.md`）起一份全新 state DB 跑 `seed_pilot`，实测：

```
LOG INFO TaskLoader initialised: .../data/pawbench-v1.0/tasks
LOG INFO Found 150 task file(s) / Loaded 150 task(s) successfully
LOG INFO builtin view stored / pilot dataset seeded
pilot: pilot_v1 | kind builtin_view | owner service | task_count 15 | categories []
resolve_tasks(PILOT_TASK_IDS) -> resolved 15, missing []
tasks_for_run -> 15        第二次 seed_pilot -> 同一行（幂等，不产生第二条数据集）
attachment mix: attached 10 / text-only 5; .png 2, .pdf 3, .xlsx 1（另 .json/.sql/.db/.md/.yml/.py/.txt）
labels.environment: closed 11, open 4      grading_type: automated 7, llm_judge 5, hybrid 3
gaps: []
```

四条构成门槛（`MIN_TASKS=15`、`MIN_ATTACHMENT_TASKS=5`、附件形态 ≥2 类、`closed`+`open` 与 `automated`+`llm_judge` 各有）在真语料上**一次通过，缺口清单为空**，`PILOT_TASK_IDS` 与 15 个真实任务 id 逐一对得上——这条结论原来只是"合成 fixture 能过"，现在是"要发布的那份语料能过"。`hybrid` 那 3 道也在内，且不是无人接管：`grading.py:265` 把 `hybrid` 与 `automated` 同路走嵌入判分，`grading.py:251` 对不认识的 `grading_type` 记 `GRADING_ERROR` 而不是猜一个分数。

**两条如实的边界，不是"验证过了"**：

1. ~~上面这些数字来自 `/tmp` 里的一次性探针，**套件里没有一条用例跑真语料**~~ → **这半句是错的，第十三批核实后更正（2026-11-11）**。`test_pilot.py:44` 就是 `REAL_CATALOGUE = REPO_ROOT / "data" / "pawbench-v1.0"`，四条用例直接读它：`test_the_shipped_seed_passes_its_own_gate`(:86) 断 `missing == []` + `len(chosen) == 15` + `composition_gaps(...) == []`，`test_the_seed_covers_the_fixture_kinds_its_comments_claim`(:101) 在真 front matter 上断三种附件形态齐 + `attached >= MIN_ATTACHMENT_TASKS`，`test_the_gate_is_the_number_the_seed_advertises`(:144) 断 `len(chosen) == MIN_TASKS`，`test_the_seed_carries_everything_a_submission_needs`(:119) 对真语料 seed 后断 `tasks_for_run` 解析出全部 15 个 id。所以"语料换版本或改掉 15 个 id 里任何一个，套件仍全绿"这句**不成立**——那几条会红。据此登记的 **L36 已作废**，它要求的两个断言（`missing` 为空、`composition_gaps` 为空）本来就在 `:86` 那条里；它另要求的"不存在即 skip"也不做，因为 `data/pawbench-v1.0` 是已跟踪的 1185 个文件（`git ls-files` 实测），任何一份 clone 里都在，为不会发生的状态写兜底只是把"语料没了"从一次响亮的红变成一次静默的 skip。**真正剩下的差别**是探针报的那些**具体数字**（closed 11／open 4、automated 7／llm_judge 5／hybrid 3、attached 10／text-only 5、.png 2／.pdf 3／.xlsx 1）套件里确实没有断言，而这是对的：门槛管的是"两类环境各有、两类判分各有、附件 ≥5 道、形态 ≥2 类"，把具体计数钉死会让每次语料扩充都变成一次改测试。**教训记在这里**：写"套件里没有 X"之前要先搜一遍 X（这次该搜的是 `REAL_CATALOGUE`），否则登记的遗留会让下一个人去补一条已经存在的用例。
2. **`categories` 是空的**（`pilot_v1` 没挂任何分类）。M2 面无问题——分类是可选标签；但 **M3 看板的分类筛选会让 pilot 在按分类浏览时不出现**，而 pilot 恰恰是最该被默认选中的那一份。这条归入遗留 4，但**不占原型三问的名额**：给 `pilot_v1` 挂哪些分类是数据决定（评测负责人在 M3 编码前定），原型只需展示"未分类"这一组存在且可点——`design_` §12 已把它单列在"不占评审名额的两件事"里。不要到 M3 才发现。

顺带一条与 L35 同源的事实：本次探针之所以能把语料指到仓库根的 `data/pawbench-v1.0`，是因为我显式传了 `builtin_root`；按 §L35 的实测，**省略 `datasets.builtin_dir` 的服务会去 `service/data/pawbench-v1.0` 找语料**，那时这里的全部数字都会变成"语料为空"。



### 4.20 M2 第十二批：第八轮检视的 10 项发现（+7 条、改 2 条，563→570）

第八轮检的是第十批＋第十一批**合起来**那份 diff（`review_acp_remote_eval.md` 第八轮：2 严重（其中一条检视者原标"严重→建议"）/ 6 一般 / 2 建议，另有 1 条资源泄漏类建议）。按门槛"严重项未修不许 commit"，两条严重项与其中三条一般/建议项在本批修掉，其余五条并入或新增遗留（L33／L34／L20+L30／L37／L38）。**563 → 570 passed, 1 warning in 19.05s**（报表 +3、数据集 +4；`test_reports.py` 42→45，`test_datasets.py` 44→48，均为 `--collect-only` 实测）。

| # | 发现 | 处理与钉住它的用例 | 反向实测 |
|---|---|---|---|
| 1 **严重** | `_write` 暂存名固定 `.{name}.part`，并发渲染互相截断：实测两线程同写一名 → `FileNotFoundError` + 4,000,028 字节的坏 JSON，而 `report()` 的 sha256／size／链接全取自它，于是被当"已缓存的正确报表"长期服务 | 已修三段：唯一暂存名（`secrets.token_hex(8)`，沿用 `exchange._stage` 的形状）、`finally` 里 `unlink(missing_ok=True)`、新增 `_ensure_report_file` 把「判在不在 + 写 + 记日志」放进 `threading.Lock` 且**输的一方返回赢家的指纹**。用例三条：`test_two_writers_of_one_report_name_use_different_temporaries`（monkeypatch `Path.replace` 记暂存名，两个线程写同一目标 → 两个名字不同、落盘那份能解析、`glob(".*.part")` 为空）、`test_a_failed_report_write_leaves_no_temporary_behind`（把目标做成目录让 `replace` 失败 → 无残留）、`test_two_requests_for_one_fingerprint_agree_on_the_file_that_landed` | 四条变异全判红：固定暂存名、不清理、**整体去锁**、输的一方报自己的数字 |
| 2 **严重→建议** | 第十一批的签名失效守卫只覆盖 custom；`builtin_view` 提前返回 `BuiltinCatalog._tasks`（永不失效）。实测改 scenario 后 custom 读到新标签、builtin 仍返回旧标签，而**同一文档里 `task.prompt` 是新文本**——一份报表两半来自两个版本 | 已修：`BuiltinCatalog` 改持**一个** `_index_pair = (signature, summaries)`，`tasks` 每次读先比签名。一个属性而不是两个，是为了让发布成为一次赋值——不需要锁，也不会读到"新签名配旧索引"；顺手删掉当时留下的无用 setter。成本实测写进 docstring：签名一遍 150 个任务 **0.55ms** vs 重新解析 **163ms**。用例 `test_a_corpus_edit_reaches_the_view_that_was_already_saved`：烘热 → 换上计数包装的 `_load_task_summaries` → 两次 describe 断 `parses == []` → 往真语料目录写新任务 → 第三次断只解析一次、新标签出现、**正文 frontmatter 与索引标签一致** | 两条变异各判红：索引退回"每进程解析一次"、索引"每次读都重解析" |
| 4 一般 | `summary is None or not path.is_file()` 分支不记日志：真实"文件被改坏"→ 改签名 → 重解析 → 任务**静默消失**（实测 `tasks_for_run` 返回 4/5，`datasets.py` **0 条 WARNING**） | 已修：循环外一条聚合 `logger.warning("dataset tasks not on disk")`，带 `dataset_id`／`task_ids`（上限 `MAX_LOGGED_TASK_IDS = 20`）／`absent_count`／`task_count`。聚合成一条是因为看板轮询报表路由、每次轮询都走到这里（检视者第 5 类点出的"循环内 warning 会被重放"）。用例 `test_a_task_that_vanished_from_disk_is_reported_once_per_run`：三个任务删两个 → 只跑一个 + **一条**记录 + 两个 id 都在里面 | 两条变异各判红：退回静默跳过、退回每条一行 |
| 7 一般 | 写侧去重没覆盖 `assign_categories`：`current.remove()` 只删第一个，遗留重复行取消归档不生效，`delete_category` 继续拒绝 | 已修，**但第一版修得不对**：只做"原样去重 + 删全部同名"，反向脚本一条变异（去重保留、删第一份）判绿——它在那份数据上是**等价变异体**，说明修复有一半是装饰。真缺口是去重比的是原样字符串、比较用的是归一化名字。改成读取时归一化，用例改摆两种拼法（`"Field Kit"` / `"field  kit"`）。用例 `test_unfiling_a_category_removes_every_copy_of_it` | 两条变异各判红：退回旧行+删第一份、`RAW_DEDUPE_ONLY`（保留"删全部"、只去掉归一化） |
| 9 建议 | `ensure_category` get→insert 非原子，两个 worker 同名分类撞 PK → `IntegrityError` → 500 | 已修：不加锁——`name` 是 `TEXT PRIMARY KEY`，让主键当仲裁者；`except sqlite3.IntegrityError` 后 `logger.info("category created elsewhere")` 并返回**落盘那一行** + `created: False`。加锁要跨进程才成立，而这里的形态是两个 daemon 共用一个 sqlite。用例 `test_the_worker_that_loses_a_category_race_reports_the_row_that_landed`：用一个真会撞主键的包装器先把行落成别人的，断言输的一方报的是赢家的行 | 改回直抛 → 判红 |
| 3／8 一般 | bodies 无缓存：真语料 150 任务下 `tasks_for_run` 0.141s／次、`task_detail` 渲染 1 个解析 40 个、`_render(md)` +80 次 `load_task`、3 次 full detail = 120 次 | **不修** → 并入 **L33**（同一根因：`results()`／`_bodies` 不接受已算好的 rows/bodies，属接口变更）。检视者另指出用例 396 把"zip 再读一次产物行"写进了断言，已记进 L33：改它时那条断言要一起改 | — |
| 5／6 一般 | `reports.py:485` 宽 `except Exception` 吞掉 `OperationalError`／`PermissionError`；`_zip` 整包两份内存（32MiB 产物 → RSS 峰值 +24MiB） | **不修** → 分别是 **L34** 与 **L20／L30**，本轮不重复编号。L20 的 `.part` 残留半边已随 #1 的 `finally` 关掉 | — |
| 10 建议 | `datasets_with_category` 为一个数字做整表读+解码，`delete_category` 每用一次付一次全表 | **不修** → 新增 **L37**（要下沉成一条 `SELECT count(*)`，得先定"JSON 列还是关联表"，与 J10 引用保护同批） | — |
| — 建议 | `delete_dataset` 不失效 `_indexes` | **不修**：条目上限 32，被删数据集的索引条目从此不可达（要读它得先有 record），只是占一格到被 FIFO 挤出；为它加失效路径等于在 `DatasetService` 与 `Store` 之间多一条通知边，换一格内存 | — |

另改两条既有用例（检视者第②问"用例有效性"的结论）：

- `test_two_workers_reaching_a_full_cache_do_not_evict_the_same_key`：检视者实测这条**确实证它声称的东西**（`/tmp/rv_a_lock.py` 把锁换成空上下文 → `KeyError('ds_0')`），但同用例的 `assert len(...) == MAX_INDEX_CACHE` 在两种实现下都是 32，**不起判别作用**。已收紧成断言 `service._indexes` 的幸存键集合：恰好一次淘汰 + 两个新键都在——无锁版本会淘汰两次，这条断言才与 `not failures` 各自独立成立。
- `test_an_unparseable_task_file_costs_its_task_and_not_the_run`：检视者判它属"看着证 A 实为 B"——它验的日志分支在真实编辑路径下不会被走到。docstring 已改写，明说它钉的是"索引说有、读的时候坏"这一支，并交叉引用 #4 的新用例。

**这一批最值得留下的两条**：① 反向脚本首跑**两条幸存者**，一条是"用例把顺序交给了调度器"（#1 的锁：两个线程在 `_render` 里各睡 0.05 s，去掉锁后输的一方那次 `is_file()` 复查通常已经能看到赢家落盘，于是与加锁版本无法区分）——补齐办法不是加断言而是**把顺序钉死**：让第一个进入 `_write` 的调用睡 0.2 s，另一个必然在它落盘前通过复查、写入自己的字节，两份 sha256 必然不同；谁被拖慢不影响结论，所以也不依赖哪个线程先跑。另一条是"变异体与修复等价"（#7），**等价变异体是关于源码的情报，不是关于脚本的情报**：它指出"原样去重 + 归一化比较"这个组合里有一半不做事。两条的完整成因记在 `reverse_checks/README.md`。② #1 那把锁之所以不是装饰，理由要写在代码里而不是只在用例里：`generated_at` 在 payload 里、**不在指纹里**，所以同一指纹的两次渲染字节不同——这句已经进了 `_ensure_report_file` 的 docstring，否则下一个人会把它当"防重复写"的优化删掉。

反向验证实收：`/tmp/reverse_round9.py` 十一条变异（BASELINE **7 passed**）→ 首跑 9/11 判红、2 条幸存者，补齐后 **11/11 判红、零幸存者**，`finally` 恢复后逐文件 sha256 一致。锚点维护如实记录：本批改写了 `tasks_for_run` 的函数体，`/tmp/reverse_round7.py` 的 `SUBSET_READ` 报 `SKIP`（= 计入幸存者），改成整段函数体锚点后重跑 → **7/7 判红**；`reverse_round6.py`（8/8）与 `reverse_round8.py`（5/5）重跑，锚点未失效、全判红、零幸存者。`reverse_round9.py` 与修正后的 `reverse_round7.py` 已按字节一致归档到 `reverse_checks/`（`cmp` identical），README 表格加了对应行。

收口重跑：全量 **570 passed, 1 warning in 19.05s**；H3 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 过滤掉 `cpd/` 后**仍为空输出**；超宽普查（**字符口径**，见 §4.13 末段——`awk 'length>100'` 数的是字节，会把 49 行误报成 188 行，本批又踩了一次，记在这里）仍 **49 行／16 文件**，本批新增 0 行；`.py` 文件数仍 **50**（后端 26／测试 24），**无新增文件**。改动文件四个：`reports.py`（唯一暂存名 + `finally` + `_ensure_report_file` 与那把锁）、`datasets.py`（`_index_pair` 签名失效 + 消失任务聚合告警 + `MAX_LOGGED_TASK_IDS` + `ensure_category` 撞主键 + `assign_categories` 读取时归一化）、`test_reports.py`（+3）、`test_datasets.py`（+4，另改 1 条既有断言与 1 条 docstring）。



### 4.21 M2 第十三批：关闭 L35（config 默认锚点）、作废 L36（+2 条、改 2 条断言，570→572）

这一批只有两件事，且都不是新功能：一处会让凭据落进 `git add` 范围的默认值，一条建立在错误前提上的遗留。

**L35：四个 fallback 的形状与它们的锚点不一致。** `_path(value, base, default)` 的 `base` 是**配置文件所在目录**（`load_config` 传 `path.parent`），而四个默认值是按**仓库根**的形状写的——`service/state.db`、`service/datasets`、`service/exchange`、`data/pawbench-v1.0`。两者拼起来，省略这些键的服务会把状态库落到 `pawbench/cpd/acp_remote_eval/service/service/state.db`：路径在 `pawbench/cpd/**` 里面，而**这个特性被 `git add` 时整棵子树都会进去**，那份 sqlite 存着 run token 与被测端点 URL。语料那条同理会指到 `service/data/pawbench-v1.0`（§4.19 末段那次探针必须显式传 `builtin_root`，就是这个原因）。

改法是把默认值改成与 `config.example.yaml` 同形——运行时产物一律 `runtime/...`，语料按包在仓库里的深度往外爬四级（`service → acp_remote_eval → cpd → pawbench`）：

| 键 | 改前（仓库根形状） | 改后（config 目录形状） |
|---|---|---|
| `service.state_db` | `service/state.db` | `runtime/state.db` |
| `datasets.custom_dir` | `service/datasets` | `runtime/datasets` |
| `exchange.exchange_dir` | `service/exchange` | `runtime/exchange` |
| `datasets.builtin_dir` | `data/pawbench-v1.0` | `../../../../data/pawbench-v1.0` |

「为什么」写进了 `_path` 的 docstring（锚点是 config 目录不是仓库根；仓库根形状的默认会把持有 run token 的库放进 `pawbench/cpd/**`，而那正是 `git add` 会捞到的地方），四级那条写在 `builtin_dir` 的调用点上（数的是包在仓库根下的层数，语料发布在根、不在包里）。理由留在代码里，是为了下一个人不会把这四个默认值当"路径写丑了"清理回去——`README.md` 里也补了一句：省略这四个键得到的就是 example 展示的同样四个位置，而 `.gitignore` 里那两条额外规则（`service/service/`、`service/data/`）覆盖的是**手写相对路径**可能产生的形状，默认值不会生成它们。

用例（`test_config.py` 25→27，`--collect-only` 实测）：

| 用例 | 钉住什么 |
|---|---|
| `test_omitting_the_paths_lands_where_the_example_says` | 只给 `public_base_url` 解析出的三个运行时路径 == `tmp_path / "runtime"/...`，且逐个断 `not path.is_relative_to(<repo>/pawbench)`——**这半句才是 L35 的判据**：不是"落在这儿对不对"，而是"绝不落在会被提交的子树里" |
| `test_the_omitted_corpus_default_is_the_shipped_one` | 锚在**真 config 目录**上时，省略 `builtin_dir` 得到的路径 == `load_config(config.example.yaml)` 的那条，且 `is_dir()` 为真。这条把"四级"这个数字钉住了：数错一级，这里就找不到语料 |

另改两条既有断言（都是把旧默认值钉死的地方）：`test_config.py:65` 的 `test_relative_paths_anchor_to_the_config_directory` 原来断 `service/state.db` 与 `data/pawbench-v1.0`，改成 `runtime/state.db` 与 `tmp_path / "data/pawbench-v1.0"`；`test_daemon.py:422` 的 `write_config` 省略 `state_db`，原来断 `seen["db"].parent == tmp_path / "service"`，改后为 `runtime`——这条是**改完源码跑全量才发现的**（`1 failed, 571 passed`），不是事先想到的：它证明旧默认值确实被用例固化过，也说明这类改动必须跑全量而不是只跑被改的那个文件。

反向验证：`reverse_checks/reverse_round10.py`（`/tmp` 那份逐字节归档，`cmp` identical）四条变异，每条把一个默认值放回旧的仓库根形状 → BASELINE **27 passed** → **4/4 判红、零幸存者**，`finally` 恢复后 `config.py` sha256 一致。锚点维护同批做了：`reverse_round9.py`（BASELINE 7 passed → **11/11**）、`reverse_round7.py`（BASELINE 5 passed → **7/7**）、`reverse_round6.py`（BASELINE 9 passed → **8/8**）、`reverse_round8.py`（BASELINE 3 passed → **5/5**）全部重跑，**无一条 `SKIP`**，本批没有打掉任何既有锚点；README 表格对应四行的"最近一次实测"已加第十三批重跑数字。

**L36：作废，因为前提经核实是错的。** 它要求"补一条真语料 pilot 构成用例 + 语料不存在即 skip"，理由是"套件里没有一条用例跑真语料"。核实结果：`test_pilot.py:44` 就定义了 `REAL_CATALOGUE = REPO_ROOT / "data" / "pawbench-v1.0"`，四条用例直接读它——`test_the_shipped_seed_passes_its_own_gate`(:86) 断 `missing == []` + `len(chosen) == 15` + `composition_gaps(...) == []`（正是 L36 要求补的两个断言）、`test_the_seed_covers_the_fixture_kinds_its_comments_claim`(:101) 在真 front matter 上断三种附件形态齐 + `attached >= MIN_ATTACHMENT_TASKS`、`test_the_seed_carries_everything_a_submission_needs`(:119) 对真语料 seed 后断 `tasks_for_run` 解析出全部 15 个、`test_the_gate_is_the_number_the_seed_advertises`(:144) 断 `len(chosen) == MIN_TASKS`。"skip" 那半也不做：语料是**已跟踪的 1185 个文件**（`git ls-files data/pawbench-v1.0` 实测），任何 clone 里都在，为不会发生的状态写兜底只会把"语料没了"从一次响亮的红变成一次静默的 skip。§4.19 边界 1 与 `review_` 的 L36 行已同步更正。**教训**：写"套件里没有 X"之前要先搜一遍 X（这次该搜的是 `REAL_CATALOGUE`），否则登记的遗留会让下一个人去补一条已经存在的用例。

收口重跑：全量 **572 passed, 1 warning in 16.37s**（反向脚本跑完后又跑了一遍，同样 572，确认 `finally` 恢复干净）；H3 `git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml requirements.txt` 过滤掉 `cpd/` 后**仍为空输出**，`git status --porcelain` 仍只有 ` M .gitignore` + 三个未跟踪目录；超宽普查（**字符口径**，`awk 'length>100'` 数的是字节、会误报，见 §4.13 末段——本批直接用 Python 数，没有再踩）仍 **49 行／16 文件**，本批新增 0 行；`.py` 文件数仍 **50**（后端 26／测试 24），**无新增文件**。改动文件五个：`service/config.py`（四个 fallback + `_path` docstring）、`test_config.py`（+2、改 1 条断言）、`test_daemon.py`（改 1 条断言）、`README.md`（省略键的落点 + `.gitignore` 覆盖范围的描述）、`.gitignore`（那两条额外规则的注释原来写的是"默认值落在 `service/service/`"，L35 关掉后这句成了假话，改成"手写相对路径仍可能产生的两种形状"——注释留着假话比没有注释更贵）。

### 4.22 M2 第十四批：判分并发的进程级污染（L39，+3 条，572→575）

**起点不是检视，是一个问题：上传的判分代码到底在哪儿执行。** 读出来的链路是
核心 `pawbench/grader.py:141` 的 `exec(grading_code, namespace)`，代码由
`_extract_grading_code`(:504-508) 从 `task.automated_checks` 的 ```python 块里正则取出，
**在服务进程内执行**；:153-181 围绕 `grade_func` 把 `sys.modules["subprocess"]`
换成一个打印 wrapper，`finally` 恢复"它当时看到的那个"。

这在 CLI 里没事（一次一题一个进程），在本服务里有事：`runtime.py:241` 每个 job
一个 asyncio task，`max_concurrent_jobs=4`，`grading.py:266` 用 `asyncio.to_thread`
把判分放进线程——最多四个补丁窗口同时开着，而补丁是进程级的。

**取证（只读探针，仓库零写入）**：`reverse_checks/probe_grader_race.py`。

- 第一版探针**自己问错了**：用 `contextlib.redirect_stdout` 在线程里捕获输出，
  而它也是进程级的，把另一条线程的输出吞掉了，5 轮只打出 1 行。那次运行不能当证据。
  改成"每个测量各起一个子进程"后重跑——子进程的真实 stdout 就是 daemon 的 stdout，
  正好是泄漏问题要问的那个东西。
- 两次运行结果不同：第一次 `intact 2/5`，第二次 `intact 0/5`（stagger
  0.00／0.02／0.05／0.10／0.15s，每题在窗口里 sleep 0.30s）。**结论不是"某个 stagger
  会坏"，而是"结果取决于线程调度，且坏了就永久坏"**：第二次 5/5 把 wrapper 留在
  `sys.modules` 里，随后一次与判分无关的 `subprocess.run(['echo', …])` 也被打印
  （`later_call_wrapped=True`、`later_stdout_echoed=True`）。
- 泄漏与 import 位置有关：`exec`(:141) 在换模块(:170) **之前**，所以脚本顶层的
  `import subprocess` 绑到真模块，只有 `grade()` 体内 import 才看得到 wrapper。
  两种各测一次：顶层 `False`、体内 `True`，打出来原样四行——
  `[grader.subprocess.run] cmd='echo FAKE-CREDENTIAL-…'` / `returncode=0` /
  `stdout='FAKE-CREDENTIAL-…\n'` / `stderr=''`。**cmd、stdout、stderr 全量进服务
  stdout，没有 task_id，没有脱敏**（marker 是探针造的假串，不是真凭据）。
- 放大：`probe_grader_nest.py` 连做 3 轮重叠判分后，一次 `echo` 打出 **3 份**
  wrapper 块（marker 出现 6 次 = 3 行 cmd + 3 行 stdout）。机制是 :153 存下的
  `_orig_subproc` 已经是上一层 wrapper，:155 `update(vars(...))` 把它的 `run` 抄进来，
  新 wrapper 又调它 → 每多一层多打一份，常驻进程里层数只增不减。

**修了什么（CPD 侧，核心零改动）**：`grading.py` 加 `_AUTOMATED_GRADING_LOCK`
（`threading.Lock`）与 `_grade_automated_exclusively`，:266 的 `to_thread` 改调它。
窗口不再重叠 → `_orig_subproc` 永远是真模块 → 恢复正确，也不再嵌套。

**代价写在常量注释里**：判分吞吐串行化（agent 并发与 judge 的 HTTP 等待都在锁外）；
**check script 挂死会占住锁**，这是新增的可用性代价。真正的解法是 M4 沙箱（遗留 5），
不是这把锁——锁只关掉"并发把进程状态改坏"这一半。

**没修的部分（诚实登记）**：单题判分仍会把脚本子进程的 cmd/stdout/stderr 打进服务
stdout；`exec` 仍在服务进程内。这两条要么改核心（需第 4 路审批）要么加沙箱，
都不是 CPD 能单方面决定的，留在遗留 5。

**用例**（`tests/cpd/acp_remote_eval/test_grading.py`，新建 3 条）：

1. `test_two_gradings_never_share_the_subprocess_patch`：第一题的 `grade()` 卡在
   `gate.wait`，确认它已进引擎后再起第二题，给 0.05s 重叠机会，然后放行；断
   `probe.peak == 1`、两题都 1.0、`sys.modules["subprocess"] is real`。
   **判据是 peak，不是"模块看起来正常"**——后者在调度幸运时也会绿（探针第一次就 2/5 绿）。
2. `test_a_raising_check_script_gives_the_lock_back`：脚本 raise → `GRADING_ERROR`
   且 `not _AUTOMATED_GRADING_LOCK.locked()`，随后一题仍判出 1.0。钉"一题坏掉不会把后面全锁死"。
3. `test_the_judge_does_not_wait_for_the_grading_lock`：测试线程持锁，`llm_judge`
   一题仍走通（`judge.calls == 1`）。钉代价边界：串行化只覆盖 check script。

观测模块写在 `tmp_path` 并 `monkeypatch.syspath_prepend`：exec 发生在 worker 线程里，
只有模块能把观测值传回用例；teardown 从 `sys.modules` 摘掉，避免跨用例串味。

**用例有效性（不改源码的反向验证）**：`reverse_checks/unlock_plugin.py` 是个 pytest
插件，**在内存里**把 `_grade_automated_exclusively` 换回裸 `_grade_automated`，
源码一个字节不动——第九轮检视正在读文件，不能跑改源码的 `reverse_*.py`。
`PYTHONPATH=/tmp … -p unlock_plugin` → **1 failed, 2 passed**，红的正是
`assert 2 == 1`（peak）；去掉插件 → 3 passed。这条变异是确定性的，不像探针依赖调度。

**收口数字**：`575 passed, 1 warning in 18.27s`（572→575）；H3 仍零核心 diff
（`git diff --name-only main -- pawbench tests data … | grep -v /cpd/` 为空）。
长行普查（口径：**字符数 > 100**，不是 `awk length` 的字节数）仍是 **49 行／16 文件**，
本批新增代码一行都没加进去。
改动文件三处：`service/grading.py`（+`import threading`、+锁与包装函数、改一处调用）、
`tests/cpd/acp_remote_eval/test_grading.py`（新建）、`reverse_checks/`（两探针 + 一插件归档）。

**另记一条与本批无关的工作区状态**：`pal_sdd/feat_siliconflow_local_eval/local_eval_report.md`
出现 49+/49- 的纯 Markdown 表格对齐改动，不是本特性产生的，未触碰、不入本批 commit。

### 4.23 M2 第十五批：judge 通道补直测（+12 条，575→587）

**缺口怎么发现的**：第十四批新建 `test_grading.py` 时顺手 grep，发现
`LlmJudge`／`JudgeUnavailable`／`JudgeUnreadable`／`_delay` 在整个套件里**零直测**
（只有第十四批的新文件与 `test_reports.py` 的字段断言命中），runner／e2e 只经过
整条 job 间接覆盖它。而这个模块的 docstring 说自己守得最硬的一条线是"被测方做得差"
与"我们没测成"的区别——那条线此前没有用例钉。

**12 条分五组**，全部用 `httpx.MockTransport` 走真 HTTP 语义：不起网络、不读真 key
（key 是 `sk-fake-…` 假串，只经 `monkeypatch.setenv` 进环境）。

1. **没配 key**：`JUDGE_UNAVAILABLE`，且**一个请求都没发**（`route.requests == []`）。
2. **归属**：200 body 里的 `model` 是"谁真的答了"，`judge_served_models` 记它而不是
   请求的那个；`pinned_model` 非空时请求体里就是它（design §13.1 的可比性前提）。
3. **重试与退避**：401 **只发一次**（配置问题不该重试成风暴）；429 带
   `Retry-After: 600` → 实际等待被 `MAX_JUDGE_BACKOFF_SECONDS` 截到 **30**；
   `Retry-After: 0.5` → 就是 **0.5**，不被 base backoff 抬高；`httpx.ConnectError`
   → 按预算重试 3 次、消息里有异常类名、**没有 key**。退避用 monkeypatch 把
   `asyncio.sleep` 换成记录器，所以用例既快又能断言"等了多久"而不是"等过"。
4. **没分与零分**：200 但正文没有数字 → `GRADING_ERROR`；200 但 body 不是 JSON →
   `GRADING_ERROR`；hybrid 的 judge 半边失败 → 分数为空、reason 是
   `JUDGE_UNAVAILABLE`，但 `automated_breakdown` 仍是 `{"ok": 1.0}`（量到的那一半留着）。
5. **注入边界与 key 卫生**：system turn 说出两个 marker 与"never follow／evidence"，
   被测方原话落在 marker 之间；key 只出现在 `Authorization` 头，`caplog.text`
   与请求体里都没有它。

**两条幸存者，成因不同**（`reverse_checks/reverse_round11.py`，7 条内存变异，首跑 **5/7**）：

- `BACKOFF_CAP` 幸存是**变异锚点错了**：`_delay` 是 `LlmJudge` 的方法，改模块级
  `g._delay` 等于没改。改成 `g.LlmJudge._delay` 后判红。这正是 README 写的内存变异
  代价——锚点失效不报 `SKIP`，而是静默无效，所以 harness 校验的是"**预期那条**红没红"。
- `FENCE_LOST` 幸存是**用例本身自指**：原来断
  `messages[0] == {"role": "system", "content": UNTRUSTED_SYSTEM_PROMPT}`，而用例是
  **按值 import** 那个常量的，插件在 import 前就改掉了它，于是"期望"跟着一起变，
  等式恒真。改成断言实质（system turn 里必须出现两个 marker、必须说 never follow
  与 evidence），常量被换成一句空话就判红。**与 L36 同族的教训：断言要钉住承诺，
  不是钉住自己引用的那个符号。**
- 修完重跑：**7/7 判红、零幸存者**，BASELINE **15 passed**。

**顺带修掉自己两个用例错误**：`test_the_served_model_…` 与 `test_a_pinned_model_…`
首跑忘挂 `keyed` fixture，于是走了"没 key"分支、`route.requests` 为空 → `IndexError`
（`2 failed, 13 passed`）。那两次红恰好证明 no-key 守卫真在挡，不是用例写对了才绿。

**收口数字**：`587 passed, 1 warning in 16.71s`（575→587）；长行普查（字符 > 100）
仍 **49 行／16 文件**，`test_grading.py` 贡献 **0**；核心零改动。改动文件两处：
`tests/cpd/acp_remote_eval/test_grading.py`（+12 条与配套 fixture／`Route`）、
`reverse_checks/reverse_round11.py`（新建，内存变异，检视期间可跑）。

### 4.24 M2 第十六批：URL 凭据脱敏直测（587→607）

`test_redact.py` 从零直测补到 20 项：query、userinfo、两者同在、幂等、
`AcpEndpoint.describe()` 及异常形状。初版 19 项通过，但有一项把
`https://key:secret/rest@host` 的密码泄漏当成“已知边界”固定下来；现在
`redact.py` 在 `@` 落到 path 时返回 `https://[redacted]`，包括正常路径中
带 `@` 的保守退化，不再把模糊路径转发到日志或报告。更新后 20 项通过。
此处牺牲该类 URL 的可读地址，换取不泄漏凭据。以上均是假串，无真密钥。

### 4.25 M2 第十七批：判分隔离和同一墙钟（607→615）

第十轮独立检视指出：模块级锁后，一个挂死的 check script 不仅挡住后续
判分，还会不断占用与 SQLite 更新、lease 心跳共用的默认线程池。改为
独立的单 worker 线程池（天然串行，避开 `sys.modules` 的并发污染），
排队判分按 job 的剩余墙钟取消；runner 从 `timeout_cap` 扣除已用时间后
传给 scorer。hybrid 的自动判分、prompt 构造与 judge 请求用**同一**单调
时钟 deadline，而不是分别重置；自动判分超时记 `GRADING_ERROR`，judge
超时记 `JUDGE_UNAVAILABLE`。judge 重试日志带 `task_id`，prompt 构造移出
事件循环，日志中的非数字 criterion 聚合一次报告，key 卫生用例扩展到
`LogRecord.extra`，退避上限用字面量 30.0 断言。

回归：`test_grading.py` 23 passed；全量 `pytest tests/cpd/acp_remote_eval -q`
**615 passed, 1 warning in 19.10s**（基线第十五批 587；redact +20，
判分 +8）；内存变异 `reverse_round11.py` 的更新后 BASELINE 23 passed，
**7/7 预期用例判红、零幸存者**。该脚本现在先校验锚点、把插件错误／超时
单列为 `HARNESS_ERROR`、保留原 `PYTHONPATH`。仍未解决的是正在执行的
check script 线程无法被取消或杀掉：超时后还可能访问 workspace，且核心
`grader.py` 仍在服务进程执行提交的代码并打印其子进程输出。上线前必须有
可杀的隔离判分沙箱，不能把 615 项全绿写成安全验收通过。

### 4.26 M4 增量：同进程 MCP 控制面（621→622）

`service/daemon.py` 在原 FastAPI 服务挂载 `/mcp/`，`mcp/server.py` 用
FastMCP Streamable HTTP 暴露目录、分类、混合选择器、内置视图创建、
提交、列表、调序、取消、状态、结果、两档详情、分页轨迹和报告链接。
只调用既有 `JobService`／`DatasetService`／`Reports`，不重复造结果结构；
每个 HTTP 请求先由同一 allowlist 的 verifier 验 Bearer，Host/Origin
只接受 `service.public_base_url` 配出的主机和源。MCP SDK 放在本特性
`requirements.txt`（`mcp>=1.30,<2`），不改核心依赖。

`test_mcp.py` 用真实 MCP SDK 的 `ClientSession` 经 ASGI transport 做
initialize、list_tools、目录读取、创建 builtin view、resolve、提交、
列队和取消；匿名 GET／POST 都是 401，创建的 owner 来自 bearer 身份。
首次全量测试发现 SDK 初始化调用 `logging.basicConfig(INFO)`，把 CLI
`--log-level warning` 的用例覆盖；入口现在把 CLI 级别传给 FastMCP。
修后全量 **622 passed, 1 warning in 17.87s**，`compileall` 成功；
`git diff --name-only main -- pawbench tests data run_bench.py pyproject.toml
requirements.txt` 无输出（CPD 新文件仍未跟踪，需以 git status 核对）。
此批尚**不包含**自定义集上传/自检 MCP 工具（下一批补上）、插件 skill、判分沙箱或
任务打标；SDK 测的是同进程协议和调用，不冒充真机通道 R 组或生产部署。

### 4.27 MCP 小包自检与注册（2026-11-19）

`pawbench_validate_dataset_package` 与 `pawbench_create_custom_dataset` 接受最多 512 KiB
的 base64 ZIP；更大的包继续用现有流式 HTTP `POST /v1/datasets/packages`。
不接受服务端文件路径，以免 MCP 客户端读取任意服务端文件。自检只解压到临时目录，
返回 `ok/task_ids/items`；注册走既有 `register_custom_archive`，owner 来自 bearer。

真实 MCP SDK 会话验证了合法 ZIP 自检、单层根目录展开、注册与 owner、
`conftest.py` 拒收且不产生记录；单元用例覆盖非法 base64 与超出工具上限。
执行：`python -m pytest tests/cpd/acp_remote_eval -q` → **623 passed, 1 warning
in 21.41s**；`python -m compileall -q pawbench/cpd/acp_remote_eval/mcp
 tests/cpd/acp_remote_eval/test_mcp.py` 通过。`git diff --check` 仅指出无关、
预存的 `pal_sdd/feat_siliconflow_local_eval/local_eval_report.md` 两处尾随空格，
本批没有触碰该文件。尚无沙箱，不能向不可信提交者开放自定义判分脚本。

### 4.28 M4 插件（skill 侧）落地（623→630，2026-11-19）

`plugins/pawbench-eval/` 现在能装：`qwenpaw plugin validate plugins/pawbench-eval` 输出
`✅ Plugin validation passed`。落地形状：`plugin.json`（`type: general`、
`entry.backend: plugin.py`）、`plugin.py`（`register_skill_provider(skills_dir=Path(__file__)
.parent / "skills", channels=["all"], enabled_by_default=True)`）、
`skills/pawbench-datasets/SKILL.md` + `templates/task.md`、根目录 `requirements.txt`、
`README.md`（安装两步 + 重装节奏 + MCP 手工配置 + 依赖位置 + 一行指向本目录）。

**与 `design_` §12 的树有一处偏差，写在这里以免下一个人以为漏了文件**：`type` 是 `general`
不是 `app`，`ui/` 与 `backend/main.py` 都还没有。`app` 类型要有 `manifest.yaml` 和 PawApp
实例，而看板正是 M3 的内容（原型三问尚未评审，遗留 4）。这一批装的是只发 skill 的插件；
M3 加 `ui/` 时把 `type` 改成 `app`、`entry` 补 `frontend`，已装的人 `install --force` 重装。

两条只有在 QwenPaw 源码里才能查到、因而写成了用例的约定：

- **依赖清单只认插件根**——`plugin_commands.py` 读 `PLUGINS_DIR/<id>/requirements.txt`，放
  `backend/` 不报错、只在对方机器上 import 失败。本插件零三方依赖，那份文件只有注释。
- **`install` 是 copytree 不是 symlink**——`skills_dir` 必须相对 `__file__` 解析；任何
  `plugins/pawbench-eval/...` 形式的推导在运行时指向不存在的地方，而插件照常"注册成功"，
  只是没有 skill。README 因此写了重装节奏（遗留 16 的后半）。

顺手修掉 SKILL.md 里一处**会静默判空**的错：原文 `Grading Criteria` 示例是普通 bullet
（`- The report ...`），而核心 `TaskLoader._extract_grading_criteria` 只认 `- [ ] …`，照抄的
`llm_judge` 任务会带着空 rubric 进 judge、每题零判据。模板改成 checkbox，并把这条约束写进
SKILL.md 正文。

`test_plugin.py` 7 条，逐条按"宿主真正解析什么"设计，不是文件存在性检查：

1. manifest 的 `id` 等于目录名（install 目标）、`type` 在 QwenPaw `PluginType` 集合内、
   `version` 三段、`entry.backend` 指向真实文件；
2. 依赖清单在插件根，且 `backend/requirements.txt` 不存在；
3. 用只记录参数的假 api 调 `plugin.register`，断言 `skills_dir` 解析到 `skills/`、
   `channels == ["all"]`、`enabled_by_default is True`；
4. 入口只锚 `__file__`（源码里不出现 `plugins/pawbench-eval` 与 `CPDPawBench`）；
5. skill 的 `name` 等于目录名，`metadata.qwenpaw.requires.mcp` **等于 `mcp/server.py` 里
   `FastMCP("<名字>")` 的那个名字**——门控名字写错时 skill 不出现在列表里，且没有任何报错；
6. skill 与模板里出现的每个 `pawbench_*` 工具名都能在 `mcp/server.py` 找到（工具改名而文档
   没跟上时，红的是这条，而不是"agent 变傻"）；
7. `templates/task.md` 原样放进 `tasks/` 后能过服务自己的 `validate_package`，且
   `## Grading Criteria` 下确实有 `- [ ]` 行。

反向验证 `reverse_checks/reverse_plugin.py`（7 条变异，文件级改写 + 逐字节还原）：BASELINE
**7 passed** → **7/7 判红、零幸存者**（TOOL_DRIFT／GATE_DRIFT／REPO_PATH／SKILLS_TYPO／
BULLET_CRITERIA／TYPE_DRIFT／DEPS_MOVED 各自红的正是预期那条），`finally` 还原后
`diff -r` 与运行前的备份一致。

用例里的 front matter 断言是自己用 yaml 重写的一份读法，因此另用 QwenPaw 的真解析器交叉
核对了一遍（`qwenpaw.agents.skill_system.store.load_skill_frontmatter_from_dir` +
`parse_skill_requirements`，QwenPaw 检出目录下直接跑）：`require_bins=[] require_envs=[]
require_mcps=['pawbench-eval'] errors=[]`，`build_skill_metadata` 也正常产出。`register(api)`
这一跳是**假 api**（只记录参数）验的，没有在真宿主上跑过——`plugin validate` 只 import
后端模块并检查 `plugin` 属性存在，不会调 `register`。这一跳要等 G4 的真机 `install`。

**这套脚本第一版把插件目录删了一半，如实记录**：`restore()` 用
`mkdir(parents=True, exist_ok=True)` 重建目录，而本机文件系统 shim 对已存在目录的
`makedirs` 抛 `EEXIST`（由 broker 直接升成异常，`exist_ok` 吞不掉），还原在第二个文件处
中断，`plugin.json`／`plugin.py`／`SKILL.md`／`README.md`／`requirements.txt`／
`__init__.py` 六个文件被删掉；已按原文重建、`qwenpaw plugin validate` 与全套用例复跑通过。
修法两条：还原只为**缺失**的目录 `mkdir`；还原后逐个 sha256 复核（原来只复核"写回去的
内容对不对"，不覆盖"根本没写回去"）。同类麻烦还有两处，与 shim 有关，写在这里省一次排查：
① 变异 `DEPS_MOVED` 原本把 `requirements.txt` 移到 `backend/`（正是要证的形状），但还原要
删掉那个新目录，而本机删除走 trash broker、对目录报 `EISDIR`——改成同目录改名，用例照样
判红，`backend/` 那半只留正向断言；② pytest 复用 `<tmp>/pytest-of-unknown` 时同一处 shim 对
`makedirs` 抛 `EEXIST`，任何用 `tmp_path` 的用例都报 `ERROR`（不是本批代码的问题，
`test_mcp.py` 单跑也复现），`--basetemp=<新目录>` 即可，脚本已内置私有 basetemp。

全量：`python -m pytest tests/cpd/acp_remote_eval -q --basetemp=/tmp/pb-full` →
**630 passed, 1 warning in 32.86s**（623 + 7）。未做：看板（M3）、`type: app` 与 `ui/`、
G4 真机 `install → 启动 → 看板` 用例、"改 SKILL.md 后已有 workspace 会不会读到新内容"的
实测（遗留 16 的第二问）、R 组真机通道。这一批只证明**宿主契约**对得上，不证明装到别人
机器上之后的运行形态。

### 4.29 M3 看板落地（630→646，2026-11-19）

`plugins/pawbench-eval/` 从"只发 skill"变成 `type: app` 的插件：
`entry.backend` 指向 `backend/main.py`（PawApp），`entry.frontend` 指向 `ui/index.js`
（单文件 ES module，`registerRoutes("pawbench-eval", …)` 注册 `/apps/pawbench-eval`）。
插件根的 `plugin.py`／`__init__.py` 已删除，避免两个入口同时像后端。
`qwenpaw plugin validate plugins/pawbench-eval` → `✅ Plugin validation passed`（v0.2.0）。

**后端只有一个代理念头**：`/v1/{rest:path}` 原样转发（同路径、同 query、同状态码、同响应体、
同错误信封），转发时注入 `Authorization`，并**丢掉**浏览器带来的 `Authorization`（只透传
`content-type`/`accept`）。另有三条小路由：`GET/PUT /config`（读/存连接，永不回显 token，
只给 `token_hint`）、`POST /config/probe`（`/healthz` + 一次 `GET /v1/jobs` 判 token 是否被拒）、
`POST /identity/{job_id}`（服务没有 whoami，token 不透明，只能从刚提交的那一行 `submitter`
学身份）、`GET /fetch?url=`（转发签名下载链接，**只允许配置的 origin**，否则是 SSRF）。
`@app.on_launch` 探活一次，连不上写一行警告带地址。

字段映射故意不做：仓库里已经有一份 `service/api.py`，再手写一份映射就有两套契约要同步，
而漂移的表现是"看板坏了"而不是"映射过期了"。

`test_plugin.py` 从 7 条涨到 23 条，新增的部分分两类：契约类（读文件）与代理类（真跑）。

**契约类（读文件，不跑代码）**：manifest `type == "app"` 且 `entry.backend`/`entry.frontend`
都存在、`meta.pawapp.entry_page == "/apps/<id>"` 且前端真的注册了这个 path；`ui/` 下只有一个
文件且没有 `import` 语句（宿主是 Blob + `import()`，相对导入会落到 blob URL 上）；前端没有
一个十六进制/`rgba()` 颜色字面量且确实用了 `useToken`；**看板调的每个端点都能在
`service/api.py` 的路由表里匹配上**（`/v1/jobs/{job_id}/detail` 这类模板按正则匹配具体路径），
反向也断言这些字面量还在 `ui/index.js` 里——任一侧改名都红，而不是 404 出现在截图上。

**代理类（真跑）**：用一个 `ThreadingHTTPServer` 记录收到的 method/path/authorization/body，
覆盖 11 条：未配置 → `412 service_not_configured`；path+query+body 原样到达；服务 token 被注入
而控制台的 bearer token 没被转发；上游 4xx 的 `error`/`message` 原样到达；连不上 → `502
service_unreachable`；`GET /config` 不含 token、留空保存不清空已存 token；probe 同时报可达性与
授权；`/fetch` 拒绝非配置 origin 且转发时**不带** bearer。`qwenpaw.pawapp` 用桩替换后 import
后端（本套件不装 QwenPaw，装了就变成在测 QwenPaw 而不是我们的用法）。

**反向验证 `reverse_checks/reverse_plugin.py` 扩到 17 条变异**：BASELINE **23 passed** →
**17/17 判红、零幸存者**，`finally` 还原后 `diff -r` 与运行前备份逐字节一致。新增的 10 条里
值得注意的是 `TOKEN_ECHO`（`/config` 多回一个 `token` 字段 → 红）、`WRONG_CREDENTIAL`（注入的
凭据差一个字符 → 红）、`ORIGIN_GUARD_OFF`（`/fetch` 的 origin 判断改成 `if False` → 红）、
`COLOUR_LITERAL`（把一个 token 换成 `#3b6ef6` → 红）、`CHMOD_OFF`（配置文件权限从 0600 放宽到
0644 → 红）、`IGNORE_OFF`（插件 `.gitignore` 不再忽略 `data/` → 红）。`SKILLS_TYPO` 第一次报 SURVIVED 是
**期望字符串写错**（用例其实红了，是我写的 `ships_the_skills_directory` 拼不上用例名
`registers_the_skills_directory`），改的是判定标签、不是用例。

**看板本身的验证**（这一批唯一"真的跑起来看过"的部分）：因为本机没有可用的完整 QwenPaw 控制台，
用一个 dev-only 预览壳（仓库外，`/tmp/pbe-preview/`）把 `window.QwenPaw` 模拟出来——React/antd/
icons 直接取 QwenPaw `console/node_modules` 的 UMD 包（版本与控制台一致），`getApiUrl` 与真宿主
同规则加 `/api` 前缀，后端是**插件自己的** `backend/main.py`（`qwenpaw.pawapp` 用桩），所以页面
调的每一条都是经过真实代理、打到 `127.0.0.1:8471` 的真服务。

用 Playwright（系统 Chrome）驱动，读写两条路径都走了：

- **提交**：混合选择器选中 `pilot_v1` → 内联面板出现 `15 道题`、`摘要 081291dd…`、
  `按来源 pilot_v1 · 15`、可展开的题目清单（resolve 真调服务，不是本地算的）；
  切「自定义区间」出现两个时间选择器，未填时提交按钮禁用并给出
  `自定义区间要填开始和结束两个时间`；切「夜间」提示窗口由服务 `schedule.night_window` 决定。
  实际提交两次（`窗口=夜间`、ACP 指向死端口）：返回 `已排队 + 队列位置 + 窗口区间`，
  提交后**身份自动从 `anderson` 学到**（页头从"身份未知"变成"身份 anderson"），
  **服务时区从响应回填成 `Asia/Shanghai`**（此前显示"未知（提交后由服务回填）"）。
- **队列**：4 行 `待起跑`，每行有提交人、窗口（`夜间固定窗 · 11-20 00:00 至 11-20 07:00`）、
  位置、以及 `⇈ ↑ ↓ ⇊ 取消 详情`；`移到队尾` 后第一行从 `regression A 103e0cab` 变成
  `regression B adf0051c`（顺序真的按 `queue_pos` 变了，服务端 `queue_pos` 60/70/75/85/95/100
  升序）；最后一行 `⇊` 是禁用态；`取消` 经 Popconfirm 确认后行数 7→6，结果区多一条`已取消`。
  调序按钮带 `aria-label`（读屏与键盘可达正是选按钮而非拖拽的理由）。
- **详情三级**：概览（描述表 / 进度 / 总分 / 场景与能力切片 / 数据集来源 / 报告）、逐题表
  （题目、能力·场景、状态、分数、耗时、写回、单题）、单题（判据逐项、产物、轨迹时间线分页）。
  `shared`/`完整版` 切换会重新拉取并重挂标题；完整版顶部固定一行
  「完整版含评分依据与他人产物，对外只发 shared 版」。
- **报告**：`md`/`json`/`html` 三种都生成成功并显示文件名、大小、sha256、过期时刻；
  下载走 `/fetch` 代理，落盘 `report-a7a44986f7b13a13-shared.md` **2371 字节**，
  与服务返回的 `size: 2371` 一致。`zip` 在 `shared` 档下拉框里显示为
  `zip（仅完整版）`且禁用，切到完整版后可选——服务端那条 `400 sensitivity_format_mismatch`
  因此不会被点出来。
- **深色**：同一个 token 体系下再走一遍，卡片、表头、面板全部跟随，无残留浅色块、无不可读文字。
- **控制台**：整轮页面只报**一条** console error，是预览壳自己的 `/favicon.ico` 404；
  没有 React 警告、没有 pageerror、没有 4xx 的业务请求。

另有一件事不是 bug、但差点变成事故，记在这里：预览壳跑完后 `plugins/pawbench-eval/data/config.json`
里留着**我的 token 与身份**，而 `install` 是 copytree——不清理就会跟着分发给所有人。已删，
并在插件根加了 `.gitignore`（`data/`、`__pycache__/`、`*.pyc`），`test_runtime_state_is_kept_out_of_
the_installed_copy` 与反向 `IGNORE_OFF` 一起守它。同时把握在插件根的一次临时 import 产生的
`backend/__pycache__` 一并清掉。

这一轮**真的抓到 4 个 bug，都是"看起来对、读起来错"的那一类**，记在这里因为截图看不出来：

1. `h(Space, 子元素…)` 少了 props 槽，第一个子元素被当成 props 吞掉——「新建视图」按钮
   在 DOM 里根本不存在，页面上看不出来（少一个按钮不像坏）。断言 `card header buttons`
   才抓到。
2. 进度条按 `(total - queued)/total` 算，全部失败的 job 显示 **100% 满绿**——与下面一行
   「失败 15」自相矛盾。改成"成功完成的比例 + 有失败时用错误色"。
3. 三级详情里的 `Descriptions` 标签列被压到两字一行（「判分方式」竖排），用
   `styles={{label:{width:96,whiteSpace:"nowrap"}}}` 修（新版 API，`labelStyle` 会报弃用）。
4. 弹框内两个「← 返回」按钮和结果区的「打开详情」在 flex 列里被拉满整宽。
   另外补掉一处逻辑坑：从完整版切回 shared 时若格式是 `zip`，原先会带着 `zip` 直接发请求，
   必然 400；切档时回退成 `md`。

**没做的 / 已知边界**（下一个人先看这段）：

- 没有在**真 QwenPaw 控制台**里跑过：预览壳模拟了 `window.QwenPaw.host`（React/antd/icons/
  路由注册都是真的，宿主的菜单挂载、主题切换、右键面板不是）。G4 的
  `install → 启动 → 看板` 仍然是唯一能证明这一跳的用例，仍未做。
- `--force` 重装后**已有 workspace** 会不会读到新 SKILL.md（遗留 16 第二问）依旧未实测。
- 窗口容量预估**只能由服务给**：`_capacity_warning` 要每题 timeout 与并发数，前端没有这两个
  数，所以不做本地预估，只在提交响应带 `window_too_small` 时把
  `窗口秒数/计划题数/平均耗时/预计可完成` 显示出来。design §12 想要的"提交前就告诉"要么由
  服务加一个 dry-run 路由，要么接受现在这种"提交后立刻说"。
- 服务没有暴露 `schedule.timezone` 的端点，所以"服务时区"在第一次提交/打开详情之前显示
  「未知（提交后由服务回填）」，不是猜的。
- token 以**明文**存在 `<plugin>/data/config.json`，权限 `0600`（`test_the_saved_token_is_not_
  world_readable` 钉住，反向 `CHMOD_OFF` 证明它会红）。这是"让页面永远拿不到 token"的代价——
  它落在一个本机文件上，而不是浏览器里；插件侧加密要有宿主密钥，现在没有。
- `GET /fetch` 的护栏是"必须等于配置的 origin"，不是完整 SSRF 加固：同一 origin 内仍可让后端
  去打任意路径，但那正是这个插件自己配的服务。

全量：`python -m pytest tests/cpd/acp_remote_eval -q --basetemp=/tmp/pb-all3` →
**646 passed, 1 warning in 41.17s**（630 + 16）。核心目录
`pawbench/ tests/ data/ run_bench.py pyproject.toml requirements.txt` 零改动。

## 5. 下一批要补的执行记录

R 组（真机 QwenPaw + `openrouter/free` judge）与 G 组（插件 validate→install→看板）目前还没有可贴的输出，落地时按 §4.1 的格式记环境、命令与逐项结论，不要只写"已验证"。
