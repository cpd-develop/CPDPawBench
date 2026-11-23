/**
 * 数据集的两级下钻：一个数据集 → 一道题。
 *
 * The list answers "what can I run".  One click below it the question becomes
 * "what is in this set, and what does each task actually ask" -- which is the
 * only way to tell a 15-task pilot from a 15-task slice of the same corpus
 * without running both.  The last step shows the question the way a report
 * shows it, because a reader comparing a set before a run with a score after
 * one should not have to learn two layouts.
 *
 * The boundary is drawn once and said once: the question, the labels, the
 * grading *kind* and weights, the criteria, the judge rubric and the fixtures
 * are here; ``automated_checks`` -- the expected values, which are the answer
 * itself -- is not, at any depth.  Reading how a task is scored is part of
 * deciding whether to run it; reading the key is not.  Where the parse comes
 * back thin, the file is one click away.
 *
 * Both levels are URLs (`?dataset=`, `?task=`), so a question can be sent to
 * whoever has to fix it instead of described over chat.
 */

import { Alert, Button, Input, Table } from "../host/antd";
import {
  api,
  DatasetDetail,
  DatasetTaskDetail,
  DatasetTaskEntry,
} from "../api";
import { describeError } from "../host/sdk";
import { useEffect, useMemo, useState } from "../host/react";
import { PreviewModal, PreviewTarget } from "../ui/preview";
import {
  CopyId,
  EmptyHint,
  Fact,
  PageHead,
  Panel,
  SectionTitle,
  StatusPill,
  bytes,
} from "../ui/primitives";

const GRADING: Record<string, string> = {
  automated: "自动判分",
  llm_judge: "LLM 判分",
  hybrid: "混合判分",
};

const NO_TASKS: DatasetTaskEntry[] = [];

function gradingLabel(value: string | null | undefined): string {
  if (!value) return "—";
  return GRADING[value] ?? value;
}

function kindLabel(kind: string): string {
  if (kind === "builtin_view") return "内置视图";
  if (kind === "custom") return "自定义包";
  return kind || "—";
}

/**
 * A dataset's filter, said in one line.
 *
 * A list keeps its length -- ``task_ids（15 项）`` -- because the ids are the
 * table below, row for row, and repeating them here is the same information
 * twice with a scrollbar in between.
 */
function filterSummary(spec: Record<string, unknown> | undefined): string {
  const parts = Object.entries(spec ?? {});
  if (!parts.length) return "无（整个语料）";
  return parts
    .map(([key, value]) =>
      Array.isArray(value) ? `${key}（${value.length} 项）` : `${key} = ${String(value)}`,
    )
    .join(" · ");
}

function scenarioOf(labels: Record<string, unknown> | undefined): string {
  const scenario = labels?.scenario;
  return typeof scenario === "string" && scenario ? scenario : "—";
}

/**
 * A long block that starts folded.
 *
 * The rubric is 1,300 characters of "what a good answer looks like".  It is the
 * reason this page exists and it is also four screens of prose, so it opens
 * closed: the question, the criteria and the attachments -- the three things
 * someone scanning a set compares across tasks -- stay above the fold.  The
 * header carries the size so the fold is not a secret, and the whole row is the
 * button, because a 12px chevron is a mean target.
 *
 * The label stays flush left with the other sub-labels; the state lives at the
 * right end, where a reader looks after deciding the block is worth opening.
 */
function Disclosure(props: {
  id: string;
  label: string;
  note?: string;
  children: unknown;
}): unknown {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        className="pbe-disclosure"
        aria-expanded={open}
        aria-controls={props.id}
        onClick={() => setOpen((prev) => !prev)}
      >
        <span className="pbe-disclosure__label">{props.label}</span>
        <span className="pbe-disclosure__note">{props.note}</span>
        <span className="pbe-disclosure__act">{open ? "收起" : "展开"}</span>
        <svg
          className="pbe-disclosure__chevron"
          width="12"
          height="12"
          viewBox="0 0 12 12"
          aria-hidden="true"
          focusable="false"
        >
          <path d="M4 2.5 8.5 6 4 9.5" fill="none" stroke="currentColor" strokeWidth="1.6" />
        </svg>
      </button>
      {open ? (
        <div id={props.id} style={{ marginTop: "var(--spacer-8)" }}>
          {props.children}
        </div>
      ) : null}
    </div>
  );
}

/** 「数据集 → 题目清单」—— one set, task by task. */
export function DatasetDetailModule(props: {
  datasetId: string;
  onBack: () => void;
  onOpenTask: (taskId: string) => void;
}): unknown {
  const [detail, setDetail] = useState<DatasetDetail | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setDetail(null);
    api
      .datasetDetail(props.datasetId)
      .then((answer) => {
        if (!alive) return;
        setDetail(answer);
        setError(null);
      })
      .catch((err) => {
        if (alive) setError(describeError(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [props.datasetId]);

  const tasks = detail?.tasks ?? NO_TASKS;
  // Serialise labels once per task, not once per keystroke per task.  Search
  // text is derived data, so deriving it here keeps the filter itself trivial.
  const haystacks = useMemo(
    () =>
      new Map(
        tasks.map((task) => [
          task.task_id,
          [task.task_id, task.name, JSON.stringify(task.labels ?? {})]
            .join(" ")
            .toLowerCase(),
        ]),
      ),
    [tasks],
  );
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return tasks;
    return tasks.filter((task) => haystacks.get(task.task_id)?.includes(needle));
  }, [tasks, haystacks, search]);

  return (
    <>
      <PageHead
        title={detail?.name || props.datasetId}
        sub={
          <>
            <span>
              {detail ? kindLabel(detail.kind) : "读取中"} · {detail?.owner || "—"} ·{" "}
              {tasks.length} 题
            </span>
            <span className="pbe-meta">
              <CopyId value={props.datasetId} label="数据集 id" keep={24} />
              {(detail?.categories ?? []).length ? (
                <>
                  <span className="pbe-meta__sep">·</span>
                  <span>{detail!.categories.join("、")}</span>
                </>
              ) : null}
            </span>
          </>
        }
        actions={<Button onClick={props.onBack}>返回数据集列表</Button>}
      />

      {error ? (
        <Alert
          type="error"
          showIcon
          message={error.code}
          description={error.message}
          style={{ marginBottom: "var(--spacer-16)" }}
        />
      ) : null}

      {detail ? (
        <Panel>
          <SectionTitle>这个集合</SectionTitle>
          <div className="pbe-cell-sub">
            {detail.description || "这个集合没有写描述。"}
          </div>
          {/* The filter is summarised rather than dumped: a builtin view's
              snapshot is a list of 15 task ids, and the table below *is* that
              list.  Printing it twice cost a screen of scroll and told nobody
              anything the rows did not. */}
          <div className="pbe-meta" style={{ marginTop: "var(--spacer-12)" }}>
            <span>分类：{(detail.categories ?? []).join("、") || "未分类"}</span>
            <span className="pbe-meta__sep">·</span>
            <span>筛选条件：{filterSummary(detail.filter_spec)}</span>
          </div>
        </Panel>
      ) : null}

      <div className="pbe-toolbar" style={{ marginTop: "var(--spacer-16)" }}>
        <span className="pbe-toolbar__label">题目</span>
        <Input.Search
          allowClear
          aria-label="搜索题目"
          placeholder="名称 / task id / 标签"
          style={{ width: 280 }}
          value={search}
          onChange={(event: any) => setSearch(event.target.value)}
        />
        <div className="pbe-toolbar__right">
          <span className="pbe-toolbar__label">
            共 {shown.length} 条{search.trim() ? `（全部 ${tasks.length}）` : ""}
          </span>
        </div>
      </div>

      <div className="pbe-table-wrap">
        <Table
          className="pbe-table"
          rowKey="task_id"
          size="middle"
          loading={loading}
          dataSource={shown}
          pagination={{ pageSize: 50, hideOnSinglePage: true }}
          onRow={(task: DatasetTaskEntry) => ({
            onClick: () => props.onOpenTask(task.task_id),
            tabIndex: 0,
            onKeyDown: (event: any) => {
              if (event.target !== event.currentTarget) return;
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                props.onOpenTask(task.task_id);
              }
            },
          })}
          locale={{
            emptyText: (
              <EmptyHint>
                {error ? "读不到这个数据集的题目" : "没有符合搜索的题目"}
              </EmptyHint>
            ),
          }}
          columns={[
            {
              title: "题目",
              dataIndex: "name",
              render: (_: unknown, task: DatasetTaskEntry) => (
                <div>
                  <div className="pbe-cell-title">{task.name || task.task_id}</div>
                  <div className="pbe-cell-sub pbe-mono">{task.task_id}</div>
                </div>
              ),
            },
            {
              title: "场景",
              dataIndex: "labels",
              width: 240,
              render: (_: unknown, task: DatasetTaskEntry) => (
                <span className="pbe-cell-sub">{scenarioOf(task.labels)}</span>
              ),
            },
            {
              title: "复杂度",
              dataIndex: "complexity",
              width: 90,
              render: (_: unknown, task: DatasetTaskEntry) => (
                <span className="pbe-cell-sub">
                  {String(task.labels?.complexity ?? "—")}
                </span>
              ),
            },
            {
              title: "判分",
              dataIndex: "grading_type",
              width: 110,
              render: (value: string) => <span className="pbe-cell-sub">{gradingLabel(value)}</span>,
            },
            {
              title: "超时",
              dataIndex: "timeout_seconds",
              width: 90,
              render: (value: number) => <span className="pbe-cell-sub">{value}s</span>,
            },
            {
              title: "附件",
              dataIndex: "attachment_count",
              width: 90,
              render: (value: number, task: DatasetTaskEntry) =>
                task.has_attachments ? (
                  <span className="pbe-pill pbe-pill--info">{value} 个</span>
                ) : (
                  <span className="pbe-cell-sub">—</span>
                ),
            },
          ]}
        />
        <div className="pbe-table__foot">
          <span>共 {shown.length} 条</span>
          <span>点一行看题干、附件与判分方式</span>
        </div>
      </div>
    </>
  );
}

/** 「一道题」—— the question, what came with it, and how it is judged. */
export function DatasetTaskModule(props: {
  datasetId: string;
  taskId: string;
  onBack: () => void;
}): unknown {
  const [detail, setDetail] = useState<DatasetTaskDetail | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState<PreviewTarget | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setDetail(null);
    api
      .datasetTask(props.datasetId, props.taskId)
      .then((answer) => {
        if (!alive) return;
        setDetail(answer);
        setError(null);
      })
      .catch((err) => {
        if (alive) setError(describeError(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [props.datasetId, props.taskId]);

  const labels = detail?.labels ?? {};
  const attachments = detail?.attachments ?? [];

  return (
    <>
      <PageHead
        title={detail?.name || props.taskId}
        sub={
          <>
            <span>
              {detail ? gradingLabel(detail.grading_type) : "读取中"} ·{" "}
              {detail ? `${detail.timeout_seconds}s` : "—"} ·{" "}
              {scenarioOf(labels)}
            </span>
            <span className="pbe-meta">
              <CopyId value={props.datasetId} label="数据集" keep={20} />
              <span className="pbe-meta__sep">/</span>
              <CopyId value={props.taskId} label="task id" keep={28} />
            </span>
          </>
        }
        actions={<Button onClick={props.onBack}>返回题目清单</Button>}
      />

      {error ? (
        <Alert
          type="error"
          showIcon
          message={error.code}
          description={error.message}
          style={{ marginBottom: "var(--spacer-16)" }}
        />
      ) : null}

      {detail?.unreadable ? (
        <Alert
          type="warning"
          showIcon
          message="这道题的 markdown 解析不了"
          description={`${detail.unreadable}。标签还在，题干读不出来；改好文件后刷新本页。`}
          style={{ marginBottom: "var(--spacer-16)" }}
        />
      ) : null}

      <Panel>
        <SectionTitle>题干</SectionTitle>
        {loading && !detail ? (
          <div className="pbe-cell-sub">读取中…</div>
        ) : (
          <pre className="pbe-block pbe-prompt">{detail?.prompt || "（这道题没有记录题干）"}</pre>
        )}
        {detail?.expected_behavior ? (
          <>
            <div style={{ height: "var(--spacer-16)" }} />
            <SectionTitle>期望行为</SectionTitle>
            <pre className="pbe-block pbe-prompt">{detail.expected_behavior}</pre>
          </>
        ) : null}
      </Panel>

      {/* The grading rules, between the question and the metadata: a reader
          deciding whether to run a task wants to know what "good" means for it,
          and this is the only place that answer lives without running it. */}
      <div style={{ marginTop: "var(--spacer-16)" }}>
        <Panel>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "var(--spacer-12)" }}>
          <SectionTitle>判分规则</SectionTitle>
          {/* The parsed fields above are a reading of the file, not the file.
              When the reading comes back thin -- a rubric in a shape the loader
              does not know -- the source is the answer, and it is one click. */}
          <Button
            size="small"
            onClick={() =>
              setPreview({ kind: "source", path: `${props.taskId}.md`, canDownload: false })
            }
          >
            看题目 markdown
          </Button>
        </div>
        <div className="pbe-facts">
          <Fact label="判分方式" value={gradingLabel(detail?.grading_type)} />
          <Fact label="权重" value={weightsOf(detail?.grading_weights)} />
        </div>

        {detail?.grading_criteria?.length ? (
          <div style={{ marginTop: "var(--spacer-12)" }}>
            <div className="pbe-cell-sub" style={{ marginBottom: "var(--spacer-6)" }}>
              判据
            </div>
            <ul
              style={{
                margin: 0,
                paddingLeft: "var(--spacer-20)",
                color: "var(--text-default)",
                lineHeight: 1.7,
              }}
            >
              {detail.grading_criteria.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        ) : null}

        {detail?.llm_judge_rubric ? (
          <div style={{ marginTop: "var(--spacer-12)" }}>
            <Disclosure
              id="task-rubric"
              label="判分细则"
              note={`${detail.llm_judge_rubric.length} 字`}
            >
              <pre className="pbe-block" style={{ maxHeight: 340, overflowY: "auto" }}>
                {detail.llm_judge_rubric}
              </pre>
            </Disclosure>
          </div>
        ) : null}

        {detail?.has_automated_checks ? (
          <div className="pbe-cell-sub" style={{ marginTop: "var(--spacer-12)" }}>
            这道题另有一段自动检查脚本，跑在判分器里。脚本里写着这道题的答案，所以不在页面上出现——上面这两块是它按什么标准给分。
          </div>
        ) : null}
        </Panel>
      </div>

      <div className="pbe-grid" style={{ marginTop: "var(--spacer-16)" }}>
        <Panel>
          <SectionTitle>标签与属性</SectionTitle>
          <div className="pbe-facts">
            <Fact label="超时" value={detail ? `${detail.timeout_seconds} 秒` : "—"} />
            <Fact label="场景" value={scenarioOf(labels)} />
            <Fact label="复杂度" value={String(labels.complexity ?? "—")} />
            <Fact label="环境" value={String(labels.environment ?? "—")} />
            <Fact label="能力" value={labelList(labels.capabilities)} />
            <Fact label="模态" value={modalityOf(labels.modality)} />
          </div>
        </Panel>

        <Panel>
          <SectionTitle>题目带的文件</SectionTitle>
          {attachments.length ? (
            <div className="pbe-rows">
              {attachments.map((item) => (
                <button
                  key={item.path}
                  type="button"
                  className="pbe-row pbe-row--file"
                  disabled={!item.present}
                  onClick={() =>
                    setPreview({ kind: "fixture", path: item.path, canDownload: true })
                  }
                >
                  <span className="pbe-row__grow pbe-mono">{item.path}</span>
                  {item.present ? null : <StatusPill tone="err" label="文件缺失" />}
                  <span className="pbe-cell-sub">
                    {item.size === null ? "—" : bytes(item.size)}
                  </span>
                  {item.present ? <span className="pbe-cell-sub">预览</span> : null}
                </button>
              ))}
            </div>
          ) : (
            <EmptyHint>这道题不带文件，只需要读题干。</EmptyHint>
          )}
        </Panel>
      </div>

      {preview ? (
        <PreviewModal
          source={{ kind: "dataset", datasetId: props.datasetId, taskId: props.taskId }}
          target={preview}
          onClose={() => setPreview(null)}
        />
      ) : null}
    </>
  );
}

/** ``{automated: 0.6, llm_judge: 0.4}`` → 「自动 60% · LLM 40%」. */
function weightsOf(weights: Record<string, number> | undefined): string {
  const parts = Object.entries(weights ?? {});
  if (!parts.length) return "—";
  const names: Record<string, string> = { automated: "自动", llm_judge: "LLM", hybrid: "混合" };
  return parts
    .map(([key, value]) => `${names[key] ?? key} ${Math.round(Number(value) * 100)}%`)
    .join(" · ");
}

function labelList(value: unknown): string {
  return Array.isArray(value) ? value.join("、") || "—" : typeof value === "string" ? value : "—";
}

function modalityOf(value: unknown): string {
  if (typeof value === "string") return value || "—";
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const type = typeof record.type === "string" ? record.type : "";
    const channels = labelList(record.channels);
    return [type, channels === "—" ? "" : channels].filter(Boolean).join(" · ") || "—";
  }
  return "—";
}
