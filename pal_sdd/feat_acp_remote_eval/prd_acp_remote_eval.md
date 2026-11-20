# PRD：ACP 远端 Agent 评测（自带环境 + 看板提交）

> **改哪里**：本仓库新增 `pawbench/cpd/acp_remote_eval/`（服务：鉴权 + 队列 + 数据交换 + 结果；ACP 远端 harness；MCP server；本地提交 CLI）、`plugins/pawbench-eval/`（QwenPaw 看板插件 + 配套 skill）、`tests/cpd/acp_remote_eval/`（用例与 fixture）。代码全部落在 `cpd/` 里，是为了把"我们项目组的特性"和"开源社区往同一个仓库合的特性"隔开——本特性对 `pawbench/`（`cpd/` 以外）、`run_bench.py`、`pyproject.toml`、`data/` **零改动**。插件由我们自行分发给开发人员，装进各人的 QwenPaw；**QwenPaw 仓库同样不产生任何改动**。
> **验收怎么判**：三个端到端场景跑通并可复现——① 内置评测集 + 远端 ACP 地址提交 → 排队 → 评分 → 看板出分；② skill 在本地准备自定义评测集 → 提交 → 评分；③ 5 个任务抢 4 个并发位 + 调序 + 取消 + 非白名单 token 被拒。判定条件写在 `test_acp_remote_eval.md` 的覆盖矩阵，逐条给证据；§6 判据 1–10 在 `acceptance_acp_remote_eval.md` §4 逐条填结论。
> **参照哪份规范**：`README.md:190`（harness 作为一等评测对象的 workspace/transcript/result 契约）、`pawbench/grader.py:105`（评分消费本地 workspace）、本仓库 `.qoder/rules/cpd-extension-over-core-edit.md`（插件走 QwenPaw 官方扩展点，不直改核心）、`.qoder/rules/qwenpal-design-system.md`（看板 UI）。插件目录形状的先例是 QwenPaw 仓库 `plugins/apps/agent-kanban/`，只读参照、不在那里落代码。

---

## 1. 为什么做

现在 PawBench 只有 `run_bench.py` 一条入口：要评测一个 agent，评测者必须自己 clone 本仓库、装依赖、准备 Docker 镜像、配 judge key，然后本地跑 CLI。三个后果：

1. **被评测方拿不到可复现的运行环境**。外部 agent/harness 作者想跑一轮，需要先理解我们的镜像与 grader 依赖，沟通成本高，结果还经常因环境差异不可比。
2. **团队内部重复劳动**。每位同学都装了 QwenPaw，但提交一轮评测要走命令行，跑完还得自己找结果文件、拼报告；150 任务 × N 模型 × M harness 的组合靠人手排期。
3. **没法测"一整套 agent + harness"**。现有 harness 适配（qwenpaw / openclaw / hermes）都是我们把 agent 装进容器再驱动，测的是"我们的环境 + 他的脚手架"。对方真正交付的东西包含自己的运行时与工具链，这部分现在测不到。

本特性把 PawBench 变成一个**常驻评测运行时服务**：别人准备好 agent 环境、给我们一个 ACP 地址，我们下发评测集、收产物、出分。评测对象是完整的 agent + harness，与本工程解耦。

## 2. 给谁做

| 角色 | 关心什么 |
|---|---|
| 团队内提交人（装了 QwenPaw 的每位同学） | 在看板点几下就能提测、能看到所有人的任务排队情况、不用碰命令行 |
| 被评测方（外部 agent/harness 作者） | 只需要暴露一个 ACP 端点 + 能访问我们的 HTTP 资源服务，不需要装我们的仓库 |
| 平台维护者 | 分数可比、题库不泄露、评分进程不被提交内容攻破 |

## 3. 两个用户场景

**场景 1 · 自定义评测集**
提交人在 QwenPaw 里用配套 skill，让本地 agent 按 `pawbench-task-authoring` 的格式要求准备评测集（任务描述、fixture、期望输出、判分方式），并登记进数据集目录（可归入某个分类）。准备好后在看板提交评测任务，填：待评测 agent 的 ACP 地址、数据集选择（见下）、评测产品、评测目的、可运行时间。

**场景 2 · 内置评测集**
提交人在看板选已有数据集。数据集是题库上的一个命名切片（例如"Office_Productivity 全量"、"pilot 15 题（含附件）"、"多模态 L3"），也可以按分类整组选。选择器允许**单个数据集多选 + 分类整组选混合**，提交前必须展示解析后的任务清单与去重结果。

两种场景都额外携带**可运行时间**：即时、夜间窗口（00:00–07:00）、自定义时间范围。两条走同一队列与同一套评分，差别只在数据集来源。

**首期 pilot 集构成（已定）**：约 15 题，且**必须覆盖带附件的任务**——纯文本题只能证明"ACP 往返 + LLM judge"通了，不能证明数据面（fixture 下载 → 远端处理 → 产物回传 → 本地重建 workspace → 判分）这条主链通了。约束为：`workspace_files` 非空的题 ≥5 个，覆盖 xlsx/png/pdf 至少两类；`by_environment` 的 closed 与 open 两档各有题；判分方式上 LLM judge 与自动化脚本各有题。这份清单直接落成第一个 `builtin_view` 数据集，不另造临时机制。

## 4. 需求映射

| # | 用户提出的要求 | 落在哪个模块 |
|---|---|---|
| 1 | 每人装 QwenPaw，插件看板提交与取结果 | 本仓库 `plugins/pawbench-eval/`（照 QwenPaw `plugins/apps/agent-kanban/` 结构，`qwenpaw plugin install` 指这个路径） |
| 2 | 能力以 MCP 开放 + 配套 skill；两场景 | 本仓库 `pawbench/cpd/acp_remote_eval/mcp/`；skill 随插件 `plugins/pawbench-eval/skills/` 由 `@app.skill_provider` 装载 |
| 3 | 白名单验证，提交携带 token，token 由本地 tool 获取 | `service/auth.py` 预留 `TokenVerifier` 接口 + 默认实现 |
| 4 | 排队、并发可配（默认 4）、排队中可调序 | `service/queue.py` |
| 5 | 看板可见全部评测任务 | `GET /jobs` 无过滤返回全部 + 前端列表 |
| 6 | 提交时设置可运行时间：即时 / 夜间（00:00–07:00）/ 自定义时间范围 | `service/schedule.py` + `job_tasks` 触发窗口 |
| 7 | skill 管理数据集（增加数据集、数据集分类）；提交时可多选单数据集、按分类选、两者混合 | `service/datasets.py` 数据集目录 + MCP dataset tools + `pawbench-datasets` skill |
| 8 | 看板支持查看评测详情（job 概览 → 逐题判分 → 轨迹与产物清单） | `GET /v1/jobs/{id}/detail`、`/tasks/{tid}/detail` + 插件详情视图 |
| 9 | MCP 支持评测详情查看与报告下载 | MCP `*_detail` / `get_report` tools + `service/reports.py`（与看板同一实现） |

## 5. 明确不做

- **不托管被评测 agent**。不提供"我们替你部署 agent"的能力；ACP 地址不可达就是任务失败，不是我们的责任边界。
- **首期不改核心文件，因此不做 `run_bench.py --agent acp`**。`AgentFactory._REGISTRY` 硬编码在 `pawbench/agents/factory.py` 里，仓库内没有任何动态注册点；挂进去要动核心 + `run_bench.py`，正是要避开的合并冲突面。本地命令行提交走 `python -m pawbench.cpd.acp_remote_eval.cli`，语义相同、入口不同；将来社区出现注册插槽，我们再把注册挪过去（design §2.1）。
- **不声明 ACP client 的 `fs/*` 与 `terminal/*` 能力**。评测运行时与远端环境解耦，文件交换只走 HTTP 数据面。这意味着我们不能保证远端 agent 在我们容器里执行命令——因此首期结果与"同环境 harness"分档呈现，不混排。
- **不做多租户细粒度权限/配额**。只有"允许访问 / 拒绝"两档，加上每用户在跑任务数的软上限。
- **首期不做全量 150 任务的 remote 榜**。只放开"判分仅依赖文本/文件产物"的任务子集，依赖预装工具链的任务打标后留到二期。
- **首期不接非 LLM-judge / 非沙箱脚本之外的自定义判分**。不接受提交者脚本在本服务进程内 `exec`。
- **不做看板 UI 的独立站点**，不做移动端。
- **运行时间只做一次性窗口，不做周期计划**。"每晚 00:00 自动跑一轮"这类 cron 化需求首期不实现；自定义时间范围解析成一个绝对开始/结束窗口，跑完即结束。（做周期的真实代价：要引入幂等键、结果版本号、模型/题库漂移对比，属于另一个特性。）
- **数据集分类只做一层扁平标签**，不做分类树、不做继承与别名。
- **不做数据集版本管理与差异对比**。`POST /v1/datasets` 覆盖式更新，历史结果只记录当时解析到的 task_id 列表（可复现，但不提供"上一版 vs 这一版"对比 UI）。
- **不做在线重判与人工改分**。详情里能看到判分依据和 judge 原文，但不提供"改个分重新入库"的入口——要复核就带证据重跑，避免榜单被手改。
- **不做报告模板自定义**。首期报告固定三块（结论与分数 / 切片对比 / 失败与缺失清单），格式支持 JSON、Markdown、HTML、zip；样式与品牌化排版留到有对外发布需求时再做。

## 6. 成功判据

1. 一个从未接触过本仓库的人，只用 ACP 地址 + 我们的资源 URL，能完成一轮内置集评测并拿到与现有 schema 一致的结果 JSON。首轮由**真实服务通道**证明：被测 agent 是本地 QwenPaw（ACP stdio，**用它本机已配好的默认模型**，我们不注入、不钉模型），judge 走 OpenRouter 免费档，不是我们自写的假 agent。
2. 判分不依赖"评测进程能访问远端文件系统"——所有结论都能从落盘的 workspace 与 transcript 复现。
3. 任何白名单外的 token 拿不到 manifest、asset、产物上传口和结果。
4. 队列行为可被脚本验证：并发上限生效、调序生效、取消生效、崩溃后任务不卡在 running。
5. 团队内至少 3 人用插件完成过一次真实评测，不需要命令行。
6. 选"夜间"提交的任务在服务时钟 00:00 之后启动、07:00 之前不启动新任务；自定义窗口同理，且窗口内并发上限依然生效。
7. 用 skill 新增数据集并归入分类后，看板选择器立即可见；以"2 个单数据集 + 1 个分类"混合提交时，解析出的任务清单与去重结果在提交前可见、提交后可核对。
8. 看板上任意 job（含他人提交的）都能进到详情视图看到：配置、窗口与数据集来源、逐题分数与耗时、失败/缺失原因、轨迹时间线与产物清单；**`shared` 与 `full` 两档对白名单内任何人都可读**（档位是外发边界，不是人员边界），MCP 用同一套实现拿到结构化详情，不需要打开看板。
9. 报告四种格式都能下载，"可分享版"经人工检查确认不含 rubric、判分代码与 fixture 正文；下载链接是一次性预签名且有 TTL，zip 内文件 sha256 可校验。
10. pilot 数据集首轮跑完，其中带附件的题（≥5、覆盖至少两类文件形态）都能从结果里看到"fixture 已下发 + 产物已回收 + 本地重建的 workspace 参与判分"三段证据，而不是只拿到一个分数。
11. 本特性交付时 `pawbench/agents/factory.py`、`run_bench.py`、`data/pawbench-v1.0/**` 相对 `main` 是零 diff，新增代码全在 `pawbench/cpd/acp_remote_eval/`（H3 留 `git diff --name-only` 原样输出）。这条是给下一个往这个仓库提 PR 的人的：他不需要理解远端评测模式就能改核心，也不会改到我们的东西。

## 7. 风险与未决

| 风险 | 说明 | 处置 |
|---|---|---|
| 可比性下降 | 远端环境自由变量（CPU/网络/预装工具） | 结果 schema 增加 `environment: byo` + 提交人自报环境指纹；榜单分档 |
| 判分失真 | 部分 `grade()` 会 `subprocess.run`，假设容器里装过东西 | 首期任务打标矩阵，不满足的任务不进 remote 榜 |
| 远程代码执行面 | 自定义集允许带脚本 → 脚本进我们进程 = RCE | 判分脚本强制在一次性隔离容器执行 |
| 提示注入 | 远端产物会拼进 judge prompt，而题库本身含 prompt injection 场景 | judge 输入做边界包裹与标注；高风险任务抽检；见 design §7 |
| 题库泄露 | HTTP 资源服务公开即被爬 | 一次性预签名 URL + TTL + 只能领本 run 分配到的 task id + 限速 |
| token 来源未定 | "本地一个 tool 获取" 的具体形态还没定 | `TokenVerifier` 接口预留，默认实现先用静态配置表，不阻塞主线 |
| 时区歧义 | "12 点到 07 点"在提交人本地和服务端可能不是同一段时间；跨时区团队会直接错开 7 小时 | 服务端单一时钟基准（默认 `Asia/Shanghai`），窗口按服务时钟判定，看板显示换算后的本地时间 |
| 免费路由不可比 | 真实测试通道用 OpenRouter 免费档：`openrouter/free` 每次可能换后端模型，judge 侧换模型 = 同一份轨迹两次打分不同 | 每次 judge 调用记录响应里的实际模型（`judge_served_models`）；模型集合不一致时看板与报告标注"与其他轮次不可比"；要对外引用分数就换成固定 model id 重跑（design §13） |
| 免费档速率 | 4 并发 × 逐题 judge 容易撞 429，表现是"分数莫名偏低" | 指数退避重试；用尽记 `judge_unavailable`，进 `tasks_errored` 而不是 0 分，也不改分母（与"没测到 ≠ 做错"同一条原则） |
| 数据集污染 | 全员可建数据集与分类（已定，见 §8 ⑤），会出现同名、语义重叠、把 pilot 集混进全量 | 分类名做规范化后去重（大小写/全半角/空格），命中相近名返回既有分类而不是新建；数据集 id 带 owner 前缀；选择器展示解析后的任务数与分类下的数据集清单，让混错可见；分类的删除仍受引用保护（被数据集引用时 409） |

**（原待确认 ①–⑤ 已于 2026-11-10 全部判定，结论见 §8；同日追加 ⑥–⑨ 四条，同样在 §8。）**

## 8. 未决项的判定结果（2026-11-10，用户拍板）

| # | 结论 | 对设计的影响 |
|---|---|---|
| ① | pilot 约 15 题即可，但**要覆盖有附件的任务** | 集成的构成约束写进 §3；数据面（fixture → 产物 → workspace 重建 → 判分）必须进 pilot，否则首轮评测检不出主链问题 |
| ② | 特性文档**不同步**到 QwenPaw 仓库，只留本仓库 `pal_sdd/feat_acp_remote_eval/` | 插件 README 里放一行指针（指向本目录），不在两处维护同一份内容——两边各写一次，三个月后必然不一致。⑦ 之后这条自动成立得更彻底：QwenPaw 仓库既不接文档也不接代码，本特性对它零改动 |
| ③ | 服务地址不是部署要求，**配置化**：开发用 `localhost`，注册 MCP 时由负责人把地址发给使用者 | 见下方硬约束：绝对 URL 只能由配置拼出，不能回退请求 Host |
| ④ | 服务时钟基准 = `Asia/Shanghai` | `schedule.timezone` 的默认值坐实；窗口 UTC 落库、看板双行换算不变 |
| ⑤ | 数据集与分类的**创建权限全员开放**（推翻此前"分类仅 `admin`"） | 权限模型简化为"白名单内可建，改/删仍限 owner 与 `admin`"；配套的去重与引用保护见 §7 数据集污染行；这条同时消除了与"不做细粒度权限"一节的自相矛盾 |
| ⑥ | 详情两档（`shared` / `full`）**白名单内全员可读**（推翻此前"`full` 限提交人"） | 访问控制收敛成一道闸（白名单 token），`read_all` scope 取消；两档差异从"人员边界"改成**外发边界**——`shared` 是可发给被评测方的那一版，`full` 只在内部复核。由此 `shared`+`zip` 的组合从 403 改成 `400 sensitivity_format_mismatch` |
| ⑦ | 插件 `pawbench-eval` **代码留本仓库** `plugins/pawbench-eval/`，由我们自行分发给开发人员（推翻此前"进 QwenPaw 仓库 `plugins/apps/`"） | QwenPaw 是交付给最终用户的产品，评测看板只发给开发人员，不该占它的发布车道；本特性因此变成单仓库交付，代价是 QwenPaw 插件契约漂移没人替我们兜——靠 G4 用例（升级后仍能 `validate` + `install`）自己跟 |
| ⑧ | 真实服务通道的被测 agent **用它本机配置的默认模型**，我们不注入 `OPENAI_*`、不钉 model id | 用户答复"真实被评测 agent 用我配置的默认模型就行" | 与被评对象的定义一致：评的是"他的 agent + harness + 他那套配置"整体，不是我们挑的某个模型。带来一条必须写进代码的后果：被测模型标识不在我们配置里，只能从 transcript/会话信息尽力提取（`subject_model_reported`），拿不到就写 `unknown`——否则分数无法归因（design §3、R7） |
| ⑨ | 本特性新增代码**一律落 `pawbench/cpd/acp_remote_eval/`**，与开源社区往同仓库合的特性隔开 | 用户要求"pawbench 也加个 cpd 放本次新增代码…开源社区开发的新特性后续还可能合并进来" | 本特性对核心零改动（含不注册进 `AgentFactory`、不改 `run_bench.py`，代价见 §5）；边界可机器检查（H3 用例断言核心目录 diff 为空）；`data/pawbench-v1.0` 题目内容同样不碰，pilot 只是引用 task_id 的视图 |

③ 带来的硬约束（写在这里是因为它容易被实现时忽略）：manifest 里的 asset 预签名 URL、产物上传口、报告下载 URL 都是**绝对地址**，只能由配置的 `service.public_base_url` 拼出，**不允许回退到请求的 `Host` 头**。原因是两条各自独立：开发时 `localhost` 拼出的链接给外部人员本就打不开（配置化才有"本地跑、别人访问"两种取值），而回退 `Host` 会把 URL 变成请求方可控的输入，等于给预签名链接做了个跳转口。启动时缺 `public_base_url` 直接失败，不给隐式默认。
