# PawBench 远端评测 使用手册

评测一个**跑在别处**的 agent：你在这边选数据集、排队、看结果，agent 在对方机器上做题，
只把轨迹和产物回传。本手册面向三类人，可以只读与自己相关的部分。

| 你是 | 读 | 你要做的事 |
|---|---|---|
| 使用者 | §3 起 | 配一次连接，之后提交 / 排队 / 读结果 |
| 管理员 | §2 | 起一次服务，签发 token，把地址和 token 发出去 |
| 出题人 | §9 | 把真实失败的任务沉淀成数据集 |

文档版本：随 `feat_acp_remote_eval` 的 M3 看板一起发布。设计与判据见同目录
`design_` / `acceptance_`。

---

## 1. 它长什么样

四层，从上到下：

```
QwenPaw 控制台 · 看板页      评测 / 数据集 / 配置  三个模块，一份报告一整页
        ↕
插件后端 · 透明代理          注入 token，转发 /v1/*，签名链接落成下载
        ↕
评测服务 HTTP /v1/*          队列 / 窗口 / 执行 / 评分 / 报告 / 数据集
        ↕
远端 ACP agent              在对方环境里做题，回传 transcript 与产物
```

看板是**三个平级的模块**，左侧一条固定导航：

| 模块 | 你在这里做什么 |
|---|---|
| **评测** | 看列表、看分数、点开一份报告；右上「＋ 新建评测」弹出提交表单 |
| **数据集** | 切内置视图、上传任务包、管理分类 |
| **配置** | 服务地址与 token、探活、报告默认档位 |

上一版把提交表单、队列、结果、数据集纵向堆在同一页，读分数要先滚过一张表单。现在提交是
一个弹窗，报告是一整页——因为它要装下题干、逐题判分和轨迹。

你只和第一层打交道。第二层存在的唯一理由是**凭据不进浏览器**：页面调的是本插件自己的
`/api/pawbench-eval/v1/...`，token 由后端在转发时加上。所以你在页面上永远看不到、也
不需要保管 token 的副本；同事来屏幕共享也看不到。

---

## 2. 一次性准备（管理员）

### 2.1 装依赖

Python 3.11+（开发与实测在 3.12）。

```bash
pip install -r pawbench/cpd/acp_remote_eval/requirements.txt
```

需要 `fastapi` + `uvicorn`（HTTP 数据面）与 `agent-client-protocol`（ACP 会话）。若被评测
agent 是通过 URL 应答而不是本地拉起进程，再加 SDK 的 transport extra：

```bash
pip install 'agent-client-protocol[http]'
```

只有 1.0 及以后才有这个 extra；0.10.x 装上去只会得到一行
`does not provide the extra 'http'` 的 warning，什么也不装（§3.3 说了为什么这很常见）。

### 2.2 写配置

```bash
cp pawbench/cpd/acp_remote_eval/service/config.example.yaml \
   pawbench/cpd/acp_remote_eval/service/config.yaml
```

有且只有三行必须改：

| 键 | 填什么 | 踩过的坑 |
|---|---|---|
| `service.public_base_url` | 被评测 agent 能访问到的本服务地址，如 `http://10.0.0.5:8471` | 不能靠请求的 Host 头推断；填 `127.0.0.1` 只在 agent 也跑本机时成立 |
| `service.bind` | 监听地址，如 `0.0.0.0:8471` | 只监听回环时，别的机器连不上 |
| `datasets.builtin_dir` | 内置语料目录，默认指向仓库 `data/pawbench-v1.0` | 相对路径锚定在配置文件所在目录 |

其余键都有默认值，可以不动：

| 键 | 默认 | 含义 |
|---|---|---|
| `service.max_concurrent_jobs` | 4 | 全团队同时跑几个，不是每人 |
| `service.max_running_per_user` | 1 | 单人上限；**超出直接拒**，不排进队列 |
| `service.max_job_seconds` | 7200 | 单 job 墙钟；到点没跑到的题记 `skipped(deadline)` |
| `schedule.timezone` | `Asia/Shanghai` | 服务时区，页面会把它和你的本地时区分开显示 |
| `schedule.night_window` | `00:00`–`07:00` | 夜间窗的两端，**由服务决定，页面不能改** |
| `schedule.hard_stop` | `false` | 关：窗内起跑的允许跑完；开：07:00 直接切断 |
| `models.judge_model` | `openrouter/free` | 唯一要配的模型；被评测端的模型不在这里 |
| `models.api_key_env` | `OPENROUTER_API_KEY` | 请求时才读环境变量，不落配置、不落库、不落日志 |

> 想让两次结果可比，就把 `models.judge_pinned_model` 钉死。免费路由每次换后端，同一个
> 分数背后可能是不同模型。

### 2.3 签发 token

```bash
cd <仓库根>
python -m pawbench.cpd.acp_remote_eval.service.auth \
    --allowlist pawbench/cpd/acp_remote_eval/service/runtime/allowlist.yaml \
    add-subject --subject alice
```

`--allowlist` 必须是配置里 `service.allowlist_file` 指的那一份，否则签了也没人认。

- token **只在这次输出里出现一次**，服务端只存哈希。没记下来就重新签发一个，旧的作废。
- `--subject` 是这个名字：它决定队列里哪一行算"你的"、谁能删自己的数据集、报告归属谁。
- 白名单文件不存在 = 空名单 = **没有人能提交**。这是故意的。

#### 给管理员账号

`admin` 不是"另一个角色"，而是 token 上多带的一个 scope。**必须和 `submit` 一起给**：

```bash
python -m pawbench.cpd.acp_remote_eval.service.auth \
    --allowlist pawbench/cpd/acp_remote_eval/service/runtime/allowlist.yaml \
    add-subject --subject ops --display-name "运维" --scope submit --scope admin
```

- `--scope` 可重复，但**默认值只在完全不写 `--scope` 时才生效**。只写 `--scope admin`
  得到的是**连读接口都进不去**的 token（所有 HTTP 路由都只校验 `submit`，读也一样），
  报 `403 insufficient_scope`。这是最容易踩的一脚。
- `admin` 只多出四件事：编辑/删除**别人**的数据集、改别人数据集的分类、取消**别人**的作业、
  调整别人作业的队列位置。它**不能加用户**——签发账号只能跑这条命令或手改 YAML，
  没有 HTTP 接口，这是刻意留的（token 只带外发放）。
- **同名再签一次是轮换，不是追加**：旧 token 立即失效，新记录的 scopes 完全覆盖旧的。
  所以要补权限就一次给全，别"先加 submit，再补一个 admin"——那会把前一个 token 废掉。
- 改完**不用重启**：服务按文件的 (mtime, size) 变化重读，日志里会出现 `allowlist re-read`。
  文件写坏了它会保留上一份记录并告警，不会把所有人踢下线。
- 看板把 token 存在 `plugins/pawbench-eval/data/config.json`；轮换后要去连接设置里重填一次。
- 查名单 `list`（只印哈希前 8 位），停用 `revoke --subject <名字>`，都不用重启。

### 2.4 起服务

```bash
python -m pawbench.cpd.acp_remote_eval \
    --config pawbench/cpd/acp_remote_eval/service/config.yaml
```

`--config` 也读 `$PAWBENCH_EVAL_CONFIG`，都不给则用包旁的 `service/config.yaml`。

一个进程同时干两件事：跑 HTTP 数据面，跑调度 tick。启动时会**结算**上次遗留的
`running` 作业——标成 `failed`（原因 `recovered`），没跑到的题 `skipped(service_restarted)`。
不续跑是有意的：上一轮的 workspace 还在盘上，续跑会把半截文件当成自己的产出。

### 2.5 验活

```bash
curl -s http://127.0.0.1:8471/healthz
# {"ok":true,"public_base_url":"http://127.0.0.1:8471","active_attempts":0}
```

`active_attempts` 是当前活着的远端会话数。这个接口不需要 token，也就不能当权限探针用。

---

## 3. 装上并连上（使用者）

### 3.1 装插件

```bash
qwenpaw plugin validate plugins/pawbench-eval
qwenpaw plugin install  plugins/pawbench-eval
```

拉取更新后要 `--force` 重装一次。`install` 是**拷贝**到 `~/.qwenpaw/plugins/pawbench-eval`，
不是软链——所以在仓库里改完，不重装就没人看得到，而且不会有人收到通知。

### 3.2 配连接

打开侧边栏 **PawBench 评测**（路由 `/apps/pawbench-eval`），点 **服务连接**：

| 字段 | 填什么 | 说明 |
|---|---|---|
| 评测服务地址 | 管理员给的 `public_base_url` | 形如 `http://10.0.0.5:8471` |
| 访问 token | 管理员签发的那串 | 粘贴后只显示"已配置"，不再回显 |
| 我的身份 | 可留空 | 用来判断队列里哪一行是你的；**首次提交后自动识别** |

点 **探测** 会一次拿到三个答案：地址通不通、token 认不认、对面是哪台服务。三种结果：

- **服务正常** — 可以用了
- **token 被拒（401/403）** — 地址对，token 错或已作废
- **连不上** — 地址错、服务没起、或中间有防火墙

配置存到插件目录下的 `data/config.json`（权限 0600）。两台机器都不方便点界面的场合
（CI、演示机）可以用环境变量顶上：

```bash
export PAWBENCH_EVAL_BASE_URL=http://10.0.0.5:8471
export PAWBENCH_EVAL_TOKEN=<token>
```

两边都设时**以页面保存的为准**——它有保存按钮，是使用者明确表达的意图。

---

### 3.3 评测本地 agent（它只会 stdio 时）

服务只认 `http://` / `https://` 的 ACP 地址，这是故意的：作业行里不能存命令，否则
一个提交者就能在服务主机上跑任意东西。但 QwenPaw 这类 agent 只说 stdio，所以插件包里
带了一个桥，把它的 stdio 变成服务能连的端口：

```bash
# 桥跑在"能 import 本包"的环境里；如果那就是服务自己的 venv，只需要补一个 transport：
pip install 'agent-client-protocol[http]'

python -m pawbench.cpd.acp_remote_eval.bridge \
    --command "/path/to/QwenPaw/venv_312/bin/qwenpaw acp" \
    --port 8472
# 提交时 ACP 地址填：http://127.0.0.1:8472/acp
```

**别把它装进被评测 agent 自己的 venv。** `http` 这个 extra 是 `agent-client-protocol`
**1.0 才有**的，而 agent 往往钉着更老的版本——QwenPaw 钉 `<0.11.0`，那个 venv 里是 0.10.1，
于是 `pip install 'agent-client-protocol[http]'` 只会打一行
`does not provide the extra 'http'`，什么都不装，`acp.http` 依然不存在，桥一起来就
`ModuleNotFoundError`。两边是在协议线上握手，不是在同一个 site-packages 里：
桥用自己的 SDK 说 HTTP，它拉起的 agent 用自己钉住的那个，所以**分开的环境才是正解**，不是绕路：

```bash
python -m venv /path/to/bridge-venv
/path/to/bridge-venv/bin/pip install 'agent-client-protocol[http]' uvicorn pyyaml
/path/to/bridge-venv/bin/python -m pawbench.cpd.acp_remote_eval.bridge \
    --command "/path/to/QwenPaw/venv_312/bin/qwenpaw acp" --port 8472
```

`pyyaml` 不是 transport 要的，是因为 import 本包会带进评分器的题目加载器。

#### 如果你就是要用同一个 venv

可以，因为 `import acp` 是**按进程**解析的。venv 里装 1.0 给桥，把老版本放在 venv 旁边，
再给 agent 一个 wrapper 把老路径前置——桥进程拿到 1.0，它拉起的 agent 拿到 0.10.1，
两边仍然只在协议线上见：

```bash
VENV=/path/to/QwenPaw/venv_312
cp -R "$VENV/lib/python3.12/site-packages/acp" "$VENV/legacy-acp/acp"   # 先留一份 0.10.1
"$VENV/bin/pip" install --upgrade 'agent-client-protocol[http]'           # 只会升这一个包

cat > "$VENV/eval-runtime.env" <<'ENV'
# 临时模型端点，只给这个 wrapper 读，不写进 ~/.qwenpaw/config.json
OPENAI_BASE_URL=https://api.example.com/v1
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-6-sol
# 可选：指定用哪个 agent 档案（见下面的"任务软入口"）
QWENPAW_ACP_AGENT=pawbench_eval
ENV
chmod 600 "$VENV/eval-runtime.env"

cat > "$VENV/bin/qwenpaw-acp-legacy" <<'SH'
#!/bin/sh
here=$(cd "$(dirname "$0")" && pwd)
export PYTHONPATH="$here/../legacy-acp${PYTHONPATH:+:$PYTHONPATH}"

runtime_env="$here/../eval-runtime.env"
if [ -f "$runtime_env" ]; then set -a; . "$runtime_env"; set +a; fi

agent_flag=""
[ -n "${QWENPAW_ACP_AGENT:-}" ] && agent_flag="--agent $QWENPAW_ACP_AGENT"

if [ -n "${OPENAI_MODEL:-}" ]; then
    exec "$here/qwenpaw" acp $agent_flag --runtime-provider openai-env "$@"
fi
exec "$here/qwenpaw" acp $agent_flag "$@"
SH
chmod +x "$VENV/bin/qwenpaw-acp-legacy"
```

桥的 `--command` 换成 `"$VENV/bin/qwenpaw-acp-legacy"`。用 QwenPaw 2.2.2 实测：
桥 1.0.0 + agent 0.10.1，`initialize` 返回 `protocol_version: 1`，`prompt` 能穿过桥。

两个代价都是真的，别忽略：

- **所有直接起 `qwenpaw acp` 的路径都会坏**——桌面壳、编辑器插件、自己的脚本，
  它们会 import 1.0 然后死在 `cannot import name 'text_block'`。这些也得走 wrapper。
- **以后对 QwenPaw 做一次 `pip install -e .`，它会把钉住的 0.10.1 装回来**，
  桥的 `acp.http` 就没了（报 `acp_transport_unavailable`）。重跑上面那行 pip 即可。

升级前先 `pip freeze > /tmp/qwenpaw-freeze.txt`；要彻底退回，`pip install
'agent-client-protocol==0.10.1'` 就行，那份 `legacy-acp/` 留着也不碍事。

桥的行为有三点要知道：

- **一个后台进程，多个连接**：`qwenpaw acp` 启动要几秒，每道题重起一次会把超时耗在启动上，
  所以桥只拉起一次，会话在连接之间多路复用；服务端发来的更新按 `session_id` 路由回开它的
  那条连接。
- **agent 的 stderr 直接透到终端**：故障原因通常就在那几行。桥不吞它。
- **`--debug`** 会打印每一次转发的调用和每一条会话绑定，排查"卡住不动"时先开它。

**它不会替你把 agent 配好。** 一个模型没配的 QwenPaw，`initialize` 会正常通过，第一次
`prompt` 才失败，报的是 `Provider 'xxx' not found` 之类——那是 QwenPaw 侧的配置问题，
不是桥或服务的。两条修法：在 QwenPaw 里配好 provider，或起 ACP 时用
`qwenpaw acp --runtime-provider openai-env` 配 `OPENAI_BASE_URL` / `OPENAI_API_KEY` /
`OPENAI_MODEL` 三个环境变量走临时 provider（上面的 wrapper 已经替你做了）。

### 3.4 让 agent 真的把文件写出来

这一步比连通更容易翻车，而且症状很像"评测器坏了"：作业 `finished`，每道题
`status=missing`、`failure_reason=no_artifacts`、`score=null`。

根因在 QwenPaw 的**任务软入口**（`loop.task.enabled`）。它是默认开着的：模型看到
"帮我做个计划 / 整理一下" 这类措辞就会调 `submit_plan`，然后**结束回合等人类 `/task confirm`**。
无人值守的评测里没有人按确认，于是作业结束、零产物。transcript 里能看到一条
`tool_call submit_plan` 和一句"计划已提交，等待用户确认"。

两件事要做：

**一是别让默认 agent 进这个流程。** 建一个专用档案，别改你平时用的那个：

```bash
/path/to/QwenPaw/venv_312/bin/qwenpaw agents create \
    --name "PawBench Eval" --agent-id pawbench_eval
```

然后把它的 `~/.qwenpaw/workspaces/pawbench_eval/agent.json` 里两处关掉：

```json
{"running": {"loop": {"task": {"enabled": false}}, "plan_execute_mode": false},
 "approval_level": "AUTO"}
```

`loop.task.enabled=false` 之后 `submit_plan` 会被直接拒绝并提示"直接执行"，模型就回到
普通的 ReAct 循环，该 `write_file` 就 `write_file`。`approval_level` 设 `AUTO` 是因为
无人值守时没有人点"允许"。

**二是注意这层覆盖是"每个 agent 一份"。** 只改 `~/.qwenpaw/config.json` 的
`agents.running.loop.task.enabled` **不生效**——`<workspace>/agent.json` 优先，而且
新建 agent 的模板默认又是 `true`。排查时直接看那个文件，别看全局的。

`QWENPAW_ACP_AGENT=pawbench_eval` 让 wrapper 起 ACP 时带上 `--agent`，桥拉起的就一直是
这个档案。

> 顺带说明：软入口关掉后，模型的工具集里仍然有 `read_file` / `write_file` /
> `execute_shell_command`，产物落在 ACP `new_session` 给的 `cwd`（也就是每道题自己的
> `exchange/jobs/<job>/<task>/attempt-N/session/`），所以收集与评分不需要额外配置。

验证方式：跑一道要求落盘的简单题（比如"把 shell 命令写到 `command.txt`"），看
`artifacts` 非空、`automated_breakdown` 有分项。实测 QwenPaw 2.2.2 + gpt-6-sol：

- `task_shell_command_generator` → `score 1.0`，5 个分项全绿
- `T088_pinbench_project_bootstrap_plan` → `score 0.833`，产物
  `output/bootstrap_plan.json`（1626 字节）

另外：桥默认只监听回环。如果你的服务不在同一台机器上，桥要让服务能访问到，`--host` 和
`public_base_url` 两边都得对得上；反过来，如果 agent 在别的机器上，就别用桥，直接给它
一个真实可访问的 ACP 地址。

## 4. 提交一次评测

在「评测」模块右上角点 **＋ 新建评测**，弹窗里填完直接提交。表单分三段：目标（地址与
标识）、选题、窗口。

### 4.1 表单项

| 字段 | 必填 | 说明 |
|---|---|---|
| ACP 地址 | 是 | 被评测 agent 的 ACP 端点，必须 `http://` 或 `https://` 开头 |
| 评测产品 | 是 | 被评测的是什么，如 `QwenPaw 2.3` |
| 评测目的 | 是 | 这次运行为什么存在，如 `夜间冒烟 / 回归 / 发版前` |
| 数据集 | 是 | 分类整组 + 单个数据集混选，下方实时显示题量 |
| 窗口 | 是 | 即时 / 夜间固定窗 / 自定义区间 |

**产品与目的不是形式主义**：一周后回头看结果，唯一能解释"这条曲线为什么跳"的就是这两栏
加上环境指纹。它们也是列表页唯一的可搜索文本。

### 4.2 选数据集

两种选法可以混用：

- **按分类整组加入** — 把某个分类下的数据集全选进来
- **挑具体的数据集** — 单个勾选

选完立刻在下方的解析面板看到结果：总题数、每条数据集贡献多少题、去重掉多少条、有没有
解析不出来的 id。**题量为 0 时提交会被拒**（`empty_selection`），不会有"跑完了但什么都没
评"的空作业。

### 4.3 选窗口

| 选项 | 行为 |
|---|---|
| **即时** | 立刻进队列，有空位就跑 |
| **夜间固定窗** | 窗的两端由服务的 `schedule.night_window` 决定（默认 00:00–07:00），页面**不带时间**；提交后把区间回填给你看 |
| **自定义区间** | 自己填开始和结束（按**本地时间**填），提交时转成绝对时刻 |

自定义区间的四条规矩，违反会被明确拒绝而不是默默改掉：

- 开始与结束都要填（`custom_window_needs_bounds`）
- 结束必须晚于开始（`window_inverted`）
- 开始不能在过去（`window_in_the_past`）
- 长度有上下限（`window_too_short` / `window_too_long`）

页面把**本地时区**和**服务时区**分两行显示，是有原因的：这两个差七小时的时候，你以为
排在了凌晨，实际排在了下午。

### 4.4 提交之后看到什么

| 信息 | 含义 |
|---|---|
| `job-xxxx` | 作业 id，后面查详情、生成报告都用它 |
| 状态 | `已排队` 或 `已登记` |
| 位置 | 你前面还有几个在做 |
| 起跑倒计时 | 夜间或自定义窗的作业，显示"还有 N 小时 N 分起跑" |
| 窗口容量提示 | "已排队，但窗口可能装不下"——**提示不阻拦**，提交仍然成功 |

容量是按 `题数 × 平均耗时 ÷ 并发` 估的，只有提交后服务才算得出来，所以它是提醒而不是
前置校验。看到这条时，要么减少题量，要么放宽窗口。

### 4.5 提交被拒的常见理由

| 错误码 | 意思 | 怎么办 |
|---|---|---|
| `per_user_limit` | 你自己已经有一个在跑（单人上限 1） | 等它结束，或先取消 |
| `empty_selection` | 选择器解析出 0 道题 | 换数据集，或检查过滤条件 |
| `selector_unknown_ids` | 选择器里有不存在的 id | 刷新数据集列表 |
| `night_window_is_fixed` | 给夜间窗硬塞了起止时间 | 夜间窗不接受自定义时间 |
| `window_in_the_past` | 开始时间已过 | 改成未来时刻或选即时 |

全局 4 个并发满了**不会拒绝你**，只会排队并告诉你前面有几个——队列就是为这个存在的。

---

## 5. 队列

队列显示**服务上所有作业**，包括别人提交的。判据是名字而不是隐藏：只有你自己的行可以调序
和取消，别人的行按钮是灰的，鼠标移上去会说明为什么。

### 5.1 七种状态

| 显示 | 内部值 | 意思 |
|---|---|---|
| 已登记 | `new` | 刚写入，还没进队列 |
| 已排队 | `queued` | 在队列里，等空位 |
| 待起跑 | `scheduled` | 时间到了/到了窗口，等调度器捞 |
| 运行中 | `running` | 正在跑，或有活着的远端会话 |
| 已完成 | `finished` | 正常结束（个别题失败也算结束） |
| 失败 | `failed` | 整个作业失败，展开看原因 |
| 已取消 | `canceled` | 你或管理员停掉了 |

### 5.2 调序

四个按钮：**移到队首 / 上移一位 / 下移一位 / 移到队尾**。

- 只有 `已排队` 和 `待起跑` 能调。**运行中不能调**，只能取消——它已经占了机器。
- 只能调自己的。别人的行按钮禁用，并写明"只能调自己的"。服务端也挡（`not_job_owner`），
  管理员是例外。
- 调序是相对移动，不是填序号。三种被拒的情形各有自己的码：状态已经变了（刚被调度走）
  是 `job_not_reorderable`；不是你的行是 `not_job_owner`；一次给了两个目标位置是
  `reorder_needs_one_target`。刷新后重试即可。

### 5.3 取消

点 **取消** 会让你确认一次，确认后：

- 已经跑完的题**保留**，结果可以照常看
- 正在跑的会话被停掉
- 状态变 `已取消`，**不可恢复**；要重跑就重新提交

---

## 6. 评测列表

列表一行一次提交。除了状态和目的，每行还给三样东西：题目进度、分数、时间。

**排序有两套规矩**：正在跑和等待中的在上面（等待中按**队列顺序**，也就是它们真正要跑的顺序，
所以 ↑↓ 挪的就是这个顺序）；已结束的在下面，**最新的在最先**——刚提交完的那次不会跑到一屏
之外去。

| 展示 | 说明 |
|---|---|
| 状态 | 运行中 / 已排队 / 待起跑 / 已完成 / 失败 / 取消；排队行额外显示队列位置 |
| 题目 | `已完成 / 总题数`，下面一条进度条；有失败时条转红 |
| 分数 | 这次评测的平均分（只算计分题），≥0.8 绿、<0.5 红 |
| 时间 | 提交时间；未结束的行显示"还有 N 小时起跑" |

顶部三个数：运行中、等待中、已完成（平均分挂在"已完成"下面，没计分题时显示 `—`）。

两个筛选口径要分清：

- **等待中**只含 `queued` 与 `scheduled`，**只有这里的行能调序**（↑ ↓）
- **已结束**含完成 / 失败 / 取消，只有这些行能出报告

**分数显示 `—` 不等于 0 分。** `—` 是"没有计分题"（全失败、全跳过、或都是
`no_artifacts`），0 分是"判了，没做对"。服务算平均分时把前者排除，列表也一样——否则
一次全挂的作业会把整体均分拉低，而它其实什么都没测到。

---

## 7. 报告（一整页，三个 Tab）

点列表任意一行进入。顶部是这份报告的身份证：目的、状态、job id（可复制）、产品、提交人、
复制链接；再往下四个数：总分、完成度、分数区间（最高–最低）、耗时。

### 7.1 总览

- 总分环 + 计分题数 + 状态分布
- 切片：能力、场景、复杂度各一条，右侧是均分
- 配置：ACP 地址、窗口、提交与开始时间
- 数据来源：这次跑了哪几个数据集、各贡献多少题
- 环境指纹：提交时自报的那份 JSON，原样保留

### 7.2 题目

一张表：题目名、task id、标签、状态、分数、耗时、`trace_id`。三个筛选口径：**异常**
（失败或 `no_artifacts`）、**低分**（<0.8）、**未计分**。

点一行进单题：

- **题干** —— 评测时发给 agent 的原文；超过 600 字符可展开。不用去翻数据集文件
- **这次执行** —— 判分方式、耗时、写回数（协议/带外）、自报模型、解析自、`trace_id`、
  `session_id`，两个 id 都能一键复制
- **判据逐项** —— 哪条过了、哪条没过，右侧是这一项的分值
- **产物** —— 文件清单、大小、sha256 前 12 位；完整版可直接下载
- **轨迹时间线** —— 每一步的时间、类型（调用 / 结果 / 输出 / 计划 / 用量…）、工具名与
  参数键。分页读，长会话不会一次糊满屏幕

### 7.3 trace_id 与 session_id

这两个 id 是**报告通往日志的入口**，所以它们放在 shared 档，不是完整版特权：

| id | 是谁的 | 拿它做什么 |
|---|---|---|
| `trace_id` | 本服务为这一次尝试生成（16 位十六进制） | `grep <trace_id> 服务日志`：建会话、下发清单、失败原因，这次尝试的每一行都带它 |
| `session_id` | 被测 agent 的会话句柄，形如 `1795156778446-y2r8j2a` | 去被评测端查它自己的日志或会话记录；两边对得上才说明是同一场 |

`session_id` 的格式值得说清楚：**位毫秒时间戳 + 一个连字符 + 7 位小写字母数字**，这本来是
agent 自己起会话时用的写法。现在是**我们先按这个写法生成一个，再通过 `session/load` 交给
agent**，让 agent 用它来命名这场会话——所以报告里印的那个 id，就是 agent 自己的历史记录里
能搜到的那个 id，"拿这个 id 去你的控制台看这场会话"是一句能照做的话，不是一次翻译。

agent 只有声明了 `loadSession` 能力才接得住这个 id。接不住（能力没声明，或明确拒绝）时它
会自己起一个，报告照样印它起的那个——仍然是正确的 grep 目标，只是不是我们挑的那个。

一次尝试一个 `trace_id`，重试会换新的——这正是它有用的地方：**两次重试的日志不会混在
一起**。升级前跑的老作业这两个字段是空的，报告里显示 `—`。

### 7.4 档位

Tab 栏右侧的 `shared / 完整版` 决定你看到哪一档：

| | shared（默认，可对外） | 完整版（内部） |
|---|---|---|
| 分数、状态、逐题表 | ✓ | ✓ |
| 题干、trace_id、session_id | ✓ | ✓ |
| 判据逐项 | ✓ | ✓ |
| 判据全文 / 期望行为 / 判分备注 | — | ✓ |
| 产物下载 | 只列清单 | ✓ |
| workspace / transcript 路径 | — | ✓ |
| 报告 zip | — | ✓ |

**完整版含判据与他人产物，对外只发 shared。** 切到完整版时页面顶部有常驻提醒，不是靠人记。

---

## 8. 导出报告

报告页第三个 Tab。选格式，点 **生成**，拿到签名链接后点 **下载**。

| 格式 | 用途 | 档位 |
|---|---|---|
| `md` | 粘进周报、MR 描述 | shared / 完整版 |
| `json` | 二次处理、进自己的看板 | shared / 完整版 |
| `html` | 直接发给人看，自带排版 | shared / 完整版 |
| `zip` | 连产物一起归档 | **仅完整版** |

报告文件里有什么：

- 总分、切片、逐题状态与分数
- **每题的题干原文**（截断到 1200 字符）
- **每题的 `trace_id` 与 `session_id`**
- 产物清单、大小

所以一份 `md` 发出去，收件人不用登录任何系统就能看懂"问了什么、怎么答的、判了多少、
要复现该搜哪个 id"。

两条规则：

- **zip 只有完整版有。** 切回 shared 时格式会自动退回 `md`，不会让你点了才报错。硬发
  shared+zip 会被拒（`sensitivity_format_mismatch`，告诉你需要哪个档位）；格式本身写错
  才是 `report_format_unsupported`。
- 签名链接**有时效**（`exchange.asset_url_ttl_seconds`，默认 3600 秒 = 1 小时）。
  过期重新生成一次，不要转发旧链接。

下载走的是插件的 `/fetch`，只允许配置过的那个服务地址——所以它不能被当成开放代理。

---

## 9. 数据集

数据集是"要跑哪些题"的载体，三种来源：

| 来源 | 是什么 | 谁维护 |
|---|---|---|
| 内置语料 | 仓库 `data/pawbench-v1.0` | 仓库 |
| 内置切片视图 | 对内置语料的一组过滤条件，创建时**快照成题 id 列表** | 任何人建，本人可改 |
| 自定义包 | 你上传的 zip 任务包 | 上传者 |

### 9.1 新建内置视图

选过滤条件（`task_ids`、`scenario`、`capability`、`complexity`、`environment`、
`modality`、`source`、`grading_type`），起个 id 和显示名，归档到分类。

- **至少给一个条件**。空过滤器等于"整份语料"，会被拒（`empty_filter`）——避免有人无意中
  建出一个几千题的数据集。
- 单个数据集最多 500 条题（`max_task_ids_per_dataset`，超出报 `too_many_tasks`）。要更大的
  切片就分成几个，用分类一次性选。
- 创建时把题 id **快照**下来，之后内置语料再变，这个视图不会跟着漂。

### 9.2 上传自定义任务包

页面路径（`POST /v1/datasets/packages`，zip 作为裸 body，元数据走 query）适合任意大小；
对话里走 MCP 的 base64 路径适合 512 KiB 以内。

| 字段 | 规则 |
|---|---|
| id | 字母或数字开头，可含 `.` `_` `-`，最长 80 位；会装进别人的选择器里，别用花名 |
| 显示名 | 给人看的名字 |
| 说明 | 一两句，会出现在列表里 |
| 归档分类 | 可多选，没合适的先建 |
| zip | 任务包，结构见 §9.3 |

服务**先校验再登记**，逐条告诉你哪个文件哪一行不对。会被拒的内容：

- 绝对路径、`..` 越界、符号链接（`package_unsafe_path`）
- `conftest.py`、`pytest.ini`、`tox.ini`、`sitecustomize.py`、`.pth`、pytest 测试模块
- 隐藏文件、不允许的扩展名
- 解压后超过磁盘配额（`package_too_large`）

这些不是洁癖：任务包里能执行的东西，就是能被评测端读到的东西。

### 9.3 任务包结构

```
mydataset/
  tasks/
    t001.md          每道题一个文件，id 唯一
  assets/            可选，题目要用的夹具
```

`tasks/t001.md` 的骨架抄 `plugins/pawbench-eval/skills/pawbench-datasets/templates/task.md`。
两个细节决定这题到底能不能判分：

- `## Grading Criteria` 下面**每行必须是 checkbox**，写成 `- [ ] ...`。写成普通列表，
  `llm_judge` 的题会带着空 rubric 进判分器，一分不给。
- `workspace_files` 的每一项有 `source`（包内路径）和 `dest`（agent 工作区路径）。没有
  附件时写成 `[]`，不要省这一行。

### 9.4 分类

分类是归档用的标签，不是权限。名字会被规范化，`Email` 和 `email` 是同一个。

- 只能删**空分类**：还挂着数据集会被拒（`category_referenced`）
- 只能删自己建的（`not_category_owner`）

### 9.5 删除的边界

- 删数据集：**跑过任务的删不掉**（`dataset_referenced`，会告诉你是哪几个 job）。否则下一
  个人会被拿去和已经不存在的文件比。
- 删别人的：只有创建者能删（`not_dataset_owner`）。

---

## 10. 命令行（等价路径）

看板能做的事，命令行都能做；每个命令就是一个有文档的请求，没有任何私门。

```bash
export PAWBENCH_EVAL_SERVER=http://127.0.0.1:8471
export PAWBENCH_EVAL_TOKEN=<token>

python -m pawbench.cpd.acp_remote_eval.cli submit \
    --acp-url http://127.0.0.1:8080/acp \
    --product QwenPaw --purpose nightly \
    --categories email --env model=qwen3-max --env build=2026.11 \
    --window immediate --watch
```

| 命令 | 做什么 |
|---|---|
| `submit` | 提交；`--watch` 跟到终态 |
| `status <job>` | 队列视角；`--json` 输出原样载荷 |
| `watch <job>` | 轮询到不动为止；`--interval` / `--timeout` |
| `detail <job>` | 评测视角；`--tier shared\|full`、`--out <file>` |
| `report <job>` | 生成并下载；`--format md\|json\|html\|zip`、`--tier` |
| `cancel <job>` | 取消，含运行中 |

退出码（适合写进 CI）：

| 码 | 含义 |
|---|---|
| 0 | 作业完成，或仍在正常推进 |
| 1 | 命令本身失败（没 token、地址错、被拒） |
| 2 | 作业终态但不是 `finished`（失败/取消） |
| 3 | watch 自己超时，作业还在跑（它保留队列位置，再 watch 一次即可） |

`report` 下载后会核对服务给的 `sha256`，不一致直接报错——截断的文件比没有文件更危险。

---

## 11. 在对话里用（skill + MCP）

插件里带一个 skill `pawbench-datasets`，可在 QwenPaw 对话里让 agent 帮你查数据集、解析
选择器、提交作业、上传任务包。

启用前提：在 QwenPaw 里配好 MCP server（QwenPaw 没有 `register_mcp*` 钩子，这一步是手工的）：

| 项 | 值 |
|---|---|
| 端点 | `<服务地址>/mcp` |
| 认证 | `Authorization: Bearer <token>` |

配好后 skill 才会出现在技能列表里，因为它在 `SKILL.md` 里声明了
`requires.mcp: ["pawbench-eval"]`。

一句提醒：让 agent 帮你做题时，**不要让它读判据、判分代码或夹具内容**——那是被评测对象
不该看到的答案。

---

## 12. 报错对照

| 现象 | 多半是 | 怎么办 |
|---|---|---|
| 页面右上"连不上" | 服务没起 / 地址错 / 防火墙 | `curl <地址>/healthz` 先验一下 |
| `token 被拒` | token 打错、已作废、或换过白名单 | 找管理员重签 |
| 提交 401 `unauthenticated` | token 的哈希不在名单里（轮换过一次也算） | 用最新签的那个；看板去连接设置重填 |
| 提交 403 `insufficient_scope` | 这个 token 没带 `submit`（只有 `admin` 就会出现） | 重签，`--scope submit --scope admin` 两个都给 |
| 提交后 502 | 插件后端到服务不通（浏览器这边是通的） | 看插件后端日志，别只看浏览器控制台 |
| `per_user_limit` | 你自己已经有一个在跑 | 等或取消 |
| `empty_selection` | 选择器没解析出题 | 换数据集 |
| `job_not_reorderable` | 该行已不是排队/待起跑（常是刚被调度走） | 刷新，看它现在的状态 |
| `not_job_owner` | 这行不是你提交的 | 只有提交者或管理员能动 |
| `job_changing` | 取消时作业还在反复变状态 | 刷新确认它当前状态，别重复点 |
| `dataset_referenced` | 数据集被作业引用过 | 改名复用，别删 |
| `sensitivity_format_mismatch` | 档位与格式不能并存（如 shared 要 zip） | 切完整版，或换 md |
| `report_format_unsupported` | 格式名写错了（只有 md/json/html/zip） | 改格式 |
| `package_unsafe_path` | zip 里有越界路径/符号链接 | 重新打包 |
| `package_invalid` | 包结构或题目元信息不合格 | 看逐项报错，对着 §9.3 改 |
| `run_token_expired` | 远端 agent 拿的会话令牌过期 | 重新提交；长时间作业把窗口放宽 |
| 报告链接 403 | 签名过期（默认 1 小时） | 重新生成 |
| 题目 `failure_reason` = `acp_agent_error` | agent **回了**错误（JSON-RPC），通信是好的；多半是它自己的模型/凭据没配好 | 看桥的终端输出，那是 agent 的 stderr |
| 题目 `failure_reason` = `acp_connection_lost` | 传输真断了：桥挂了、端口不对、agent 进程退出 | 先 `curl` 一下桥的地址，再看桥的终端 |
| 题目 `failure_reason` = `no_artifacts`，但解答看起来"做完了" | agent 调了 `submit_plan` 在等人类确认（见 §3.4） | 关掉 `loop.task.enabled`，或换专用评测 agent |
| `Provider 'xxx' not found` | QwenPaw 没配 provider，或没带 `--runtime-provider` | 见 §3.3 结尾 |
| 本地 agent 提交后每题都 `failed` | agent 自己的模型/凭据没配好 | 同上，看桥的终端 |

排错顺序永远这三步：**`/healthz` 通不通 → token 认不认 → 插件后端到服务通不通**。
三层里任何一层断了，页面上的表现都长得很像。

---

## 13. 已知边界

诚实列出来，免得你按"应该有"去用：

1. **自定义数据集的判分代码在服务进程内跑**（沙箱还没做）。不要上传不可信作者写的判分代码。
2. **窗口容量是提交后告知，不是提交前预估**。要预估得服务加一条 dry-run 路由。
3. **哪些内置题适合远端，仍是手工清单**，没有按敏感度自动分级。
4. **服务没有 whoami 接口**，身份靠"首次提交后从 `submitter` 学到"。换 token 后第一次提交
   前，"我的"这一列可能标错行。
5. **`pilot_v1` 的分类是空的**，进去看到"未分类"是正常的，不是配置漏了。
6. 单题 transcript 很长时按页读，一次只取一屏；想全文就用报告里的 zip。
7. **stdio agent 必须经过桥**（§3.3），服务本身不接受命令形式的提交。桥是运维工具，
   不是服务的一部分：它重启后旧作业连不上，正在跑的任务会失败。
8. **被评测 agent 自己的"需要人类确认"会被记成失败，而且这是对的**。评测端没有人在按
   确认键，所以 agent 停下来等确认 = 它没交作业。要区分"评测器坏了"和"agent 卡住了"，
   看 `failure_reason`：`no_artifacts` 配一条 `submit_plan` 的 transcript 就是后者
   （处理见 §3.4）。
9. **`env_fingerprint` 只存不校验**：写进去的 model / agent_id 不会被拿去和实际跑的进程
   对照，转录里另有一份 agent 自报的 `subject_model_reported` 可以交叉核对。

---

## 附录 A：提交请求长什么样

命令行与看板发的是同一个请求，可以直接 `curl` 复核：

```json
{
  "acp_url": "http://127.0.0.1:8080/acp",
  "product": "QwenPaw",
  "purpose": "nightly",
  "selector": { "categories": ["email"], "datasets": [] },
  "window": { "kind": "immediate" },
  "env_fingerprint": { "model": "qwen3-max", "build": "2026.11" }
}
```

`POST /v1/jobs` 回 `201`，带 `job_id`、`status`、`queue_pos`；容量不足时多一个 `warning`
对象，但**仍是 201**。

## 附录 B：常用接口

| 方法 路径 | 用途 |
|---|---|
| `GET /healthz` | 探活，无 token |
| `GET/POST /v1/jobs` | 列作业 / 提交 |
| `GET /v1/jobs/{id}` | 单个作业的队列视角 |
| `PATCH /v1/jobs/{id}` | 调序（`before_id` / `after_id` / `queue_pos` 三选一） |
| `POST /v1/jobs/{id}/cancel` | 取消 |
| `GET /v1/jobs/{id}/detail?sensitivity=` | 详情，`shared` 或 `full` |
| `GET /v1/jobs/{id}/tasks/{task}/detail` | 单题详情 |
| `GET /v1/jobs/{id}/results` | 切片结果 |
| `GET /v1/jobs/{id}/report?format=&sensitivity=` | 报告**签名链接**（不是字节） |
| `GET /v1/jobs/{id}/transcript?task_id=&attempt=&cursor=` | 轨迹分页 |
| `GET/POST /v1/datasets`、`PUT/DELETE /v1/datasets/{id}` | 数据集 |
| `POST /v1/datasets/resolve` | 解析选择器，不落库 |
| `POST /v1/datasets/packages` | 上传自定义包（裸 zip + query 元数据） |
| `GET/POST/DELETE /v1/dataset-categories` | 分类 |
