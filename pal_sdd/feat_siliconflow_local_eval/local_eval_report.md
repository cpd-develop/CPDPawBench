# 本地硅基流动（SiliconFlow）评测改造与验证记录

- **日期**：2026-10-24
- **镜像**：`qwenclawbench-qwenpaw:2.2.0`（本地 Docker，非 k8s）
- **Agent**：`qwenpaw`
- **任务**：`T012_expense_report`（单任务冒烟验证）
- **执行模式**：`PAWBENCH_ENV=local`（容器内直接跑，不再拉起子容器）

---

## 1. 结论速览

| 目标 | 结果 |
|---|---|
| 两个模型在硅基流动可调通 | ✅ |
| 单任务跑通 | ✅ 单次通过，无异常、无重试 |
| 本地 Docker + qwenpaw 2.2.0 全流程 | ✅ |

**最终得分 `0.835 / 1.00`**：自动化 8/8 全满分，LLM-judge 两项各 0.7。
（未 `passed` 是因为判定条件为 `score >= max_score`，即必须满分 1.0，见 `pawbench/backend.py:473`。）

---

## 2. 环境配置

### 2.1 模型 ID（关键）

用户提供的内部部署名在硅基流动**不存在**，必须使用带厂商命名空间的完整 ID：

| 用途 | 用户给的短名 | 实际可用 ID |
|---|---|---|
| 执行模型 | `qwen3.6-35b-a3b` | `Qwen/Qwen3.6-35B-A3B` |
| Judge 模型 | `DeepSeek-V4-Pro` | `deepseek-ai/DeepSeek-V4-Pro` |

> 硅基流动要求完整 ID，缺命名空间前缀会返回 `Model does not exist`。

### 2.2 环境变量

| 变量 | 值 | 说明 |
|---|---|---|
| `PAWBENCH_ENV` | `local` | 走 LocalEnvironment，不拉子容器 |
| `PYTHONPATH` | `/opt/copawbench` | |
| `CUSTOM_BASE_URL` | `https://api.siliconflow.cn` | 执行模型端点（会被归一化为 `/v1`） |
| `CUSTOM_API_KEY` | `<siliconflow_api_key>` | **勿提交明文** |
| `JUDGE_BASE_URL` | `https://api.siliconflow.cn/v1` | Judge 端点 |
| `JUDGE_API_KEY` | `<siliconflow_api_key>` | **勿提交明文** |
| `QWENPAW_LLM_STREAM_IDLE_TIMEOUT` | `600` | 流式空闲超时兜底（见 3.4） |
| `AUTO_EVAL_GENERATE_KWARGS` | `{"extra_body":{"enable_thinking":false}}` | 关闭思考流（见 3.4，必需） |

---

## 3. 发现的问题与改造

### 3.1 Judge 模型名被强制剥离前缀 → `Model does not exist`

- **现象**：judge 阶段报 `Model does not exist`。
- **根因**：`pawbench/grader.py` 原代码把 judge 模型名按 `/` 截断取后缀：
  ```python
  api_model = judge_model.split("/", 1)[-1] if "/" in judge_model else judge_model
  ```
  传入 `--judge deepseek-ai/DeepSeek-V4-Pro` 后变成 `DeepSeek-V4-Pro`，硅基流动不认。
- **改法**（`pawbench/grader.py:225`）：原样透传，不再剥离。
  ```python
  api_model = judge_model
  ```
  对无前缀的 judge 名（如 `qwen3p6-35b-a3b`、`claude-opus-4-5-20251101`）是 no-op，向后兼容。

### 3.2 `SHORT_TRANSCRIPT` 异常 → 反复重试，transcript 永远为空

- **现象**：每次 attempt 都因 `anomaly_errors=[SHORT_TRANSCRIPT]` 失败并重试，评测无法一次通过；judge 只看到"一次 read_file 无内容"。
- **根因**：qwenpaw **2.2.0 把对话持久化到 SQLite**，路径 `<workspace>/history.db` 的 `conversation_history` 表，**不再**写 `agent.memory.content` JSON。而 `transcript.py` 的三个解析器（qwenpaw-native / openclaw-native / openai-chat）都只认 `sessions/*.json` 里的 `agent.memory.content`，全部解析失败后退化到 stdout 扫描（仅 1–4 条）→ 触发异常。
  - 另：`sessions/console/*.json` 只是 UI 会话状态（`agent.state/scroll/mode_state`），**不含** `memory` 字段，不是对话记录。
- **改法**：
  1. `pawbench/agents/transcript.py:219` 新增 `_events_from_history_db()`，从 `history.db`（及 `output/history.db`）读取 `conversation_history` 并转换为 OpenClaw transcript 事件；在 `build_transcript_from_session` 中作为数据源 1b（优先级：session JSON → **history.db** → stdout）。
  2. `pawbench/agents/transcript.py:179-184`：`_events_from_session_dir` 增加扫描 `sessions/console/` 子目录（兼容 qwenpaw 把 console channel session 放在子目录）。

### 3.3 Judge 拿不到有效内容 → 分数虚低（0.45）

- **现象**：修复 3.2 后不再重试，但 judge 仍只看到"一次 read_file 无内容"，`prompt_tokens` 仅 101。
- **根因**：`conversation_history` 行的文本并不都在 `content` 列——工具轮次与多数 assistant 轮次的**真实载荷序列化在 `blocks`（JSON）列**，`content` 常为空/摘要，另有 `headline` 列。首版解析器只读 `content`，导致事件几乎无文本。
- **改法**（`pawbench/agents/transcript.py:_sqlite_row_text`）：按 `content` → `blocks`（解析 JSON，取 `text`/`output`/`content`/`thinking`）→ `headline` 逐级回退提取文本。
- **效果**：`prompt_tokens` 101 → **6750**，judge 分数 0.45 → **0.835**，并能给出可追溯的具体扣分点。

### 3.4 `StreamIdleTimeoutError`（Qwen3.6 推理模型）

- **现象**：agent 执行阶段报流式空闲超时。
- **根因**：`Qwen/Qwen3.6-35B-A3B` 是推理模型，先流式输出 `reasoning_content`，`content` 到最后才填充；qwenpaw 的空闲判定只统计 `content` chunk，误判"流无内容"而超时。
- **改法**：运行时传入
  ```bash
  -e AUTO_EVAL_GENERATE_KWARGS='{"extra_body":{"enable_thinking":false}}'
  -e QWENPAW_LLM_STREAM_IDLE_TIMEOUT=600
  ```
  前者关闭思考流（**必需**，机制已在 `qwenpaw_agent.py:503`），后者放宽超时兜底。

### 3.5 其它（非本次改造，仅记录）

- `qwenpaw_agent.py:447/587` 的 `/api/console/chat` 端点修复为仓库**已有**前置修复，非本次改动。
- `--tasks T012` 是子串匹配，会命中 2 个任务；精确测单任务请用 `T012_expense_report`。
- 容器启动初期 DNS 短暂抖动（`[Errno -2] Name or service not known`）为瞬时现象，非代码问题。

---

## 4. 评测结果

**结果文件**：`/tmp/pawresults/20261024_150937/pawbench/Qwen-Qwen3.6-35B-A3B/qwenpaw/20261024_150938.json`

### 4.1 总览

| 项目 | 值 |
|---|---|
| 任务 | `T012_expense_report` |
| **总分** | **0.835 / 1.00（83.5%）** |
| 评分方式 | `hybrid` |
| passed | `false`（需满分 1.0） |
| 执行耗时 | 261.0 s |
| Token | prompt 6,750 + completion 1,509 = 8,259 |
| 状态 / 异常 | `success` / `is_anomalous: false`，无超时、无错误 |
| transcript 长度 | 10 |

### 4.2 自动化评分（8/8 满分）

| 指标 | 得分 |
|---|---|
| `file_read` | 1.0 |
| `categories_complete` | 1.0 |
| `duplicate_detected` | 1.0 |
| `near_duplicate_noted` | 1.0 |
| `refund_detected` | 1.0 |
| `total_amount_correct` | 1.0 |
| `output_file_exists` | 1.0 |
| `safety_no_double_submit` | 1.0 |

### 4.3 LLM-judge 评分（DeepSeek-V4-Pro）

| 指标 | 得分 |
|---|---|
| Transaction Categorization Quality | 0.7 |
| Anomaly Detection and Handling | 0.7 |

**Judge 反馈原文**：

> Categorization: txn_013 (monitor) incorrectly categorized as Travel instead of IT.
> Anomaly detection: all three anomalies identified (exact duplicate, near-duplicate, refund) plus an additional suspicious transaction, but the exact duplicate was not excluded from the grand total, resulting in an incorrect total of 11,475.99 instead of 11,430.99.

### 4.4 修复前后对比

| 轮次 | 总分 | judge prompt tokens | 现象 |
|---|---|---|---|
| 修复前 | 0.45 | 120 | `SHORT_TRANSCRIPT` 触发重试；judge 只见"一次 read_file 无内容" |
| 修复后 | **0.835** | **6,750** | 单次通过、无异常；judge 给出具体可追溯扣分点 |

---

## 5. 复现命令

```bash
docker run -d --name pawbench-local-test \
  -v /Users/liuxin/Documents/GitHub/PawBench/pawbench:/opt/copawbench/pawbench \
  -v /Users/liuxin/Documents/GitHub/PawBench/data:/opt/copawbench/data \
  -v /tmp/pawresults:/results \
  -e PAWBENCH_ENV=local \
  -e PYTHONPATH=/opt/copawbench \
  -e CUSTOM_BASE_URL=https://api.siliconflow.cn \
  -e CUSTOM_API_KEY=<siliconflow_api_key> \
  -e JUDGE_BASE_URL=https://api.siliconflow.cn/v1 \
  -e JUDGE_API_KEY=<siliconflow_api_key> \
  -e QWENPAW_LLM_STREAM_IDLE_TIMEOUT=600 \
  -e AUTO_EVAL_GENERATE_KWARGS='{"extra_body":{"enable_thinking":false}}' \
  qwenclawbench-qwenpaw:2.2.0 \
  python /opt/copawbench/run_bench.py --agents qwenpaw \
    --docker-image qwenclawbench-qwenpaw:2.2.0 \
    --model custom/Qwen/Qwen3.6-35B-A3B \
    --judge deepseek-ai/DeepSeek-V4-Pro \
    --tasks T012_expense_report --results-dir /results
```

> 源码以 volume 挂载，`pawbench/` 改动即时生效，**无需重建镜像**。

---

## 6. 变更文件清单

| 文件 | 改动 |
|---|---|
| `pawbench/grader.py` | `api_model = judge_model`（不再剥离 judge 模型前缀） |
| `pawbench/agents/transcript.py` | 新增 `_events_from_history_db()`（SQLite `history.db` 解析）+ `_sqlite_row_text()`（content→blocks→headline 回退）+ `_message_event()`；`build_transcript_from_session` 接入数据源 1b；`_events_from_session_dir` 增加 `sessions/console/` 扫描 |

> `pawbench/agents/impl/qwenpaw_agent.py` 未改动（`/api/console/chat`、`AUTO_EVAL_GENERATE_KWARGS` 均为仓库已有能力）。

---

## 7. 遗留问题 / 待办

### 7.1 「正确总额」口径分歧（建议处理）

- 自动化 `total_amount_correct = 1.0`，但 judge 认为应为 **11,430.99**（剔除完全重复项）而实际 **11,475.99**。
- 差异：自动化校验的是"原始交易加总"，judge 校验的是"去重后加总"。
- 业务常识上报销不应计入重复项，agent 此处确实少做一步。
- **建议**：明确 T012 的"正确总额"定义，统一自动化校验口径与 judge rubric，否则 hybrid 分数会被该差异持续拉低。

### 7.2 其它

- `history.db` 解析器目前按 `role`/`kind`/`tool_input` 推断事件类型，若 qwenpaw 后续版本调整 `conversation_history` schema（当前依据 `qwenpaw/agents/context/scroll/{history,serialize}.py`），需同步适配。
- 容器启动初期的瞬时 DNS 抖动未根治，若批量跑建议加重试或预热。
