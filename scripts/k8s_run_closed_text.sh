#!/usr/bin/env bash
# =============================================================================
# k8s_run_closed_text.sh
#
# 在公司 k8s 上逐个跑 PawBench 任务：
#   - 自动筛选 environment=closed 且 modality.type=text（纯 text）的任务
#   - 每个任务启动一个独立 pod，跑完删 pod，再启下一个（强隔离、串行）
#   - 结果通过 hostPath 落盘到宿主机，脚本末尾汇总分数
#
# 前置：
#   1) 已按 pal_sdd/feat_siliconflow_local_eval/local_eval_report.md 的流程打好
#      镜像并 push 到 registry（默认 2.2.1-patched）
#   2) 当前机器能执行 kubectl 且能访问 hostPath 宿主机路径
#   3) 设置 API_KEY（或 OPENLLM_API_KEY）环境变量
#
# 用法：
#   DRY_RUN=1  ./k8s_run_closed_text.sh          # 只打印将运行的任务，不真正提交
#   RESUME=1   ./k8s_run_closed_text.sh          # 跳过 summary 中已有结果的任务
#   ./k8s_run_closed_text.sh                     # 正式跑
# =============================================================================
set -uo pipefail

# ============================== 配置（可环境变量覆盖） ==============================
NAMESPACE="${NAMESPACE:-default}"
IMAGE="${IMAGE:-registry.cic.cmbchina.cn/inference/qwenclawbench-qwenpaw:2.2.1-patched}"
TASKS_DIR="${TASKS_DIR:-/home/ops/lj/lx/PawBench/data/pawbench-v1.0/tasks}"
DATA_HOST="${DATA_HOST:-/home/ops/lj/lx/pawbench-v1.0}"
# 宿主机上的 pawbench/ 代码目录；挂进容器覆盖镜像内同名目录，
# 这样改 runner 代码（如 qwenpaw_agent.py）无需重建镜像即可生效。
PAWCODE_HOST="${PAWCODE_HOST:-/home/ops/lj/lx/PawBench/pawbench}"
RESULTS_HOST="${RESULTS_HOST:-/home/ops/lj/lx/results}"
MODEL="${MODEL:-custom/qwen3p6-35b-a3b}"
JUDGE="${JUDGE:-qwen3p6-35b-a3b}"
CUSTOM_BASE_URL="${CUSTOM_BASE_URL:-http://open-llm.uat.cmbchina.cn/llm/qwen3p6-35b-a3b}"
JUDGE_BASE_URL="${JUDGE_BASE_URL:-http://open-llm.uat.cmbchina.cn/llm/qwen3p6-35b-a3b/v1}"
API_KEY="${API_KEY:-${OPENLLM_API_KEY:-}}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# 默认用 t020 版模板（含 pawcode 挂载）；想退回纯镜像模式可指向
# $SCRIPT_DIR/../k8s/pawbench-task-pod.yaml
TEMPLATE="${TEMPLATE:-$SCRIPT_DIR/../k8s/pawbench-task-pod-t020.yaml}"
WORK_DIR="${WORK_DIR:-/tmp/k8s_bench_$(date +%Y%m%d_%H%M%S)}"
DRY_RUN="${DRY_RUN:-0}"
RESUME="${RESUME:-1}"
POD_TIMEOUT="${POD_TIMEOUT:-1800}"   # 单 pod 最大等待秒数（超时即删并标记 Timeout）

[ -z "$API_KEY" ] && { echo "ERROR: 请设置 API_KEY 或 OPENLLM_API_KEY 环境变量"; exit 1; }
[ -f "$TEMPLATE" ] || { echo "ERROR: 模板不存在: $TEMPLATE"; exit 1; }
mkdir -p "$WORK_DIR"
TASK_LIST="$WORK_DIR/tasks.txt"
SUMMARY="$WORK_DIR/summary.tsv"

# ============================== 1. 筛选 closed + text 任务 ==============================
python3 - "$TASKS_DIR" "$TASK_LIST" <<'PY'
import sys, glob, os, yaml
tasks_dir, out = sys.argv[1], sys.argv[2]

def find(d, key):
    """递归查找 dict/list 中所有 key 对应的 value。"""
    if isinstance(d, dict):
        for k, v in d.items():
            if k == key:
                yield v
            yield from find(v, key)
    elif isinstance(d, list):
        for i in d:
            yield from find(i, key)

selected = []
for f in sorted(glob.glob(os.path.join(tasks_dir, "*.md"))):
    txt = open(f, encoding="utf-8").read()
    if not txt.startswith("---"):
        continue
    try:
        fm = txt.split("---", 2)[1]
        meta = yaml.safe_load(fm)
    except Exception:
        continue
    if not isinstance(meta, dict):
        continue
    # environment: 优先 labels.environment，回退到任意层级
    env = (meta.get("labels") or {}).get("environment")
    if env is None:
        env = next((v for v in find(meta, "environment") if isinstance(v, str)), None)
    # 纯 text: labels.modality.type == text 或 顶层 input_modality == text-only
    modality_type = ((meta.get("labels") or {}).get("modality") or {}).get("type")
    input_modality = meta.get("input_modality")
    is_closed = (env == "closed")
    is_text = (modality_type == "text") or (input_modality == "text-only")
    if is_closed and is_text:
        selected.append(os.path.basename(f)[:-3])  # 去掉 .md

with open(out, "w") as fh:
    fh.write("\n".join(selected) + ("\n" if selected else ""))
print(f"[select] 命中 {len(selected)} 个 closed+text 任务 -> {out}", file=sys.stderr)
for s in selected:
    print("  - " + s, file=sys.stderr)
PY

mapfile -t TASKS < "$TASK_LIST"
echo "待运行任务数: ${#TASKS[@]}"

# ============================== 2. 逐个调度 ==============================
: > "$SUMMARY"
printf "task\tscore\tstatus\n" >> "$SUMMARY"

for stem in "${TASKS[@]}"; do
  # k8s 资源名必须满足 RFC 1123 subdomain：仅小写字母、数字、'-'、'.'，
  # 且首尾为字母数字。任务 ID 含下划线和大写，这里规范化成合法 pod 名；
  # --tasks 仍传原始 stem，保证任务 ID 不被改动。
  pod="pawbench-$(printf '%s' "$stem" | tr '[:upper:]_' '[:lower:]-')"
  yaml="$WORK_DIR/${stem}.yaml"

  # ---- 渲染 pod yaml ----
  python3 - "$TEMPLATE" "$yaml" "$pod" "$NAMESPACE" "$IMAGE" "$CUSTOM_BASE_URL" \
                "$API_KEY" "$JUDGE_BASE_URL" "$MODEL" "$JUDGE" "$RESULTS_HOST" \
                "$DATA_HOST" "$PAWCODE_HOST" "$stem" <<'PY'
import sys
(tpl, out, pod, ns, image, cbase, key, jbase,
 model, judge, rhost, dhost, pawcode, stem) = sys.argv[1:15]
s = open(tpl).read()
repl = {
    "__POD_NAME__": pod, "__NAMESPACE__": ns, "__IMAGE__": image,
    "__CUSTOM_BASE_URL__": cbase, "__API_KEY__": key, "__JUDGE_BASE_URL__": jbase,
    "__MODEL__": model, "__JUDGE__": judge, "__RESULTS_HOST__": rhost,
    "__DATA_HOST__": dhost, "__PAWCODE_HOST__": pawcode,
    "__TASK_STEM__": stem,
}
for k, v in repl.items():
    s = s.replace(k, v)
open(out, "w").write(s)
PY

  # ---- resume: 已跑过的跳过 ----
  if [ "${RESUME}" = "1" ] && grep -q "^${stem}\b" "$SUMMARY" 2>/dev/null; then
    echo "[skip] $stem 已在汇总中，跳过"; continue
  fi

  if [ "${DRY_RUN}" = "1" ]; then
    echo "[dry-run] 将运行 $pod (--tasks $stem)"; continue
  fi

  echo "===== [$stem] apply ====="
  kubectl apply -f "$yaml"

  # ---- 等待 pod 完成 ----
  start=$(date +%s)
  status="Unknown"
  while true; do
    phase=$(kubectl get pod "$pod" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Gone")
    if [ "$phase" = "Succeeded" ] || [ "$phase" = "Failed" ]; then
      status="$phase"; break
    fi
    if [ "$phase" = "Gone" ]; then
      status="Gone"; break
    fi
    now=$(date +%s)
    if [ $((now - start)) -gt "$POD_TIMEOUT" ]; then
      echo "[timeout] $pod 超过 ${POD_TIMEOUT}s，删除"
      kubectl delete pod "$pod" -n "$NAMESPACE" --ignore-not-found
      status="Timeout"; break
    fi
    sleep 20
  done

  # ---- 收集日志与分数 ----
  kubectl logs "$pod" -n "$NAMESPACE" > "$WORK_DIR/${stem}.log" 2>&1 || true
  score=$(grep -oE "score=[0-9.]+/1.00" "$WORK_DIR/${stem}.log" 2>/dev/null | tail -1 | grep -oE "[0-9.]+" | head -1)
  printf "%s\t%s\t%s\n" "$stem" "${score:-NA}" "$status" >> "$SUMMARY"

  # ---- 删除 pod（释放资源，再启下一个）----
  kubectl delete pod "$pod" -n "$NAMESPACE" --ignore-not-found || true
  echo "[done] $stem -> status=$status score=${score:-NA}"
done

# ============================== 3. 汇总 ==============================
echo ""
echo "===== 汇总 (${SUMMARY}) ====="
cat "$SUMMARY"

# 若本机可访问 hostPath 结果目录，额外扫描所有结果 json 做交叉核对
if [ -d "$RESULTS_HOST" ]; then
  echo ""
  echo "===== 宿主机结果目录交叉核对 (${RESULTS_HOST}) ====="
  python3 - "$RESULTS_HOST" <<'PY'
import sys, glob, json, os
base = sys.argv[1]
rows = []
for f in glob.glob(os.path.join(base, "**", "*.json"), recursive=True):
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    for r in d.get("results", []):
        rows.append((r.get("task_id"), r.get("score"), r.get("grading_type")))
print(f"扫描到 {len(rows)} 条结果记录")
for t, s, g in rows:
    print(f"  {t}\t{s}\t{g}")
PY
fi

echo ""
echo "工作目录: $WORK_DIR"
