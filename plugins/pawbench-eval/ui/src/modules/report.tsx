/**
 * 报告 — one page, three tabs.
 *
 * Why a page and not the modal it used to be: a report now carries the task
 * text.  A reader who cannot see the question cannot argue with the answer, and
 * sending them to another system to find it is how a report stops being read.
 * The modal also kept the list behind it, which made "compare these two runs"
 * a sequence of opening and closing rather than two links.
 *
 * The two ids on every task are the other half of that argument.  A score
 * nobody can trace back to a run is a number, not a measurement, so
 * ``trace_id`` (ours, 16 hex per attempt) and ``session_id`` (the agent's own
 * handle) sit in the shared tier rather than behind 完整版 — the person who
 * forwards this document is usually forwarding it to whoever owns the agent.
 */

import {
  Alert,
  Button,
  Input,
  Modal,
  Progress,
  Radio,
  Segmented,
  Table,
  Tabs,
  Tooltip,
} from "../host/antd";
import { api, JobDetail, ReportFormat, Sensitivity, TaskEntry, TranscriptEvent, TranscriptPage } from "../api";
import { describeError, download, saveBlob } from "../host/sdk";
import { useEffect, useMemo, useState } from "../host/react";
import { useFeedback } from "../ui/feedback";
import {
  CopyId,
  EmptyHint,
  Fact,
  Figure,
  PageHead,
  Panel,
  SectionTitle,
  StatusPill,
  bytes,
  duration,
  fixed,
  jobStatus,
  json,
  stamp,
  taskStatus,
} from "../ui/primitives";

type TaskFilter = "all" | "bad" | "low" | "unscored";

const FORMATS: { value: ReportFormat; label: string; hint: string; fullOnly?: boolean }[] = [
  { value: "md", label: "Markdown", hint: "一页读完，适合贴进 issue 或 wiki" },
  { value: "html", label: "HTML", hint: "同内容带样式，适合发给不装工具的人" },
  { value: "json", label: "JSON", hint: "原始字段，适合二次处理" },
  { value: "zip", label: "ZIP", hint: "报告 + 产物原文件", fullOnly: true },
];

function isBad(task: TaskEntry): boolean {
  return task.status !== "finished" || Boolean(task.failure_reason);
}

function lowScore(task: TaskEntry): boolean {
  return typeof task.score === "number" && task.score < 0.8;
}

export function ReportModule(props: {
  jobId: string;
  sensitivity: Sensitivity;
  onSensitivity: (value: Sensitivity) => void;
  onBack: () => void;
}): unknown {
  const feedback = useFeedback();
  const [detail, setDetail] = useState<JobDetail | null>(null);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("overview");
  const [openTask, setOpenTask] = useState<TaskEntry | null>(null);
  const [filter, setFilter] = useState<TaskFilter>("all");
  const [search, setSearch] = useState("");
  const [format, setFormat] = useState<ReportFormat>("md");
  const [exporting, setExporting] = useState(false);
  const [lastExport, setLastExport] = useState<{ filename: string; size: number; url: string } | null>(
    null,
  );

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .detail(props.jobId, props.sensitivity)
      .then((next) => {
        if (!alive) return;
        setDetail(next);
        setError(null);
      })
      .catch((err) => {
        if (!alive) return;
        setError(describeError(err));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [props.jobId, props.sensitivity]);

  const tasks = detail?.tasks ?? [];

  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return tasks.filter((task) => {
      if (filter === "bad" && !isBad(task)) return false;
      if (filter === "low" && !lowScore(task)) return false;
      if (filter === "unscored" && typeof task.score === "number") return false;
      if (!needle) return true;
      return [task.task_id, task.name, task.labels?.scenario, task.trace_id, task.session_id]
        .join(" ")
        .toLowerCase()
        .includes(needle);
    });
  }, [tasks, filter, search]);

  async function generate(): Promise<void> {
    setExporting(true);
    try {
      const link = await api.report(props.jobId, format, props.sensitivity);
      setLastExport({ filename: link.filename, size: link.size, url: link.url });
      // The service hands back a presigned URL; the bytes never pass through
      // the request that rendered them.
      window.open(link.url, "_blank", "noopener");
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setExporting(false);
    }
  }

  const scores = tasks.map((task) => task.score).filter((value): value is number => typeof value === "number");
  const high = scores.length ? Math.max(...scores) : null;
  const low = scores.length ? Math.min(...scores) : null;
  // The detail route answers with ``{mean, count, best, worst}``; the queue
  // route answers with a bare number.  Both mean "the score of this job".
  const summary = typeof detail?.score === "number" ? null : detail?.score ?? null;
  const mean = typeof detail?.score === "number" ? detail.score : (summary?.mean ?? null);
  const scoreCount = summary?.count ?? scores.length;

  const linkFor = `${window.location.origin}${window.location.pathname}?job=${props.jobId}`;

  const progress = detail?.progress ?? {};
  const byStatus = progress.by_status ?? {};
  const statusRows = Object.entries(byStatus);
  const totalTasks = progress.total ?? tasks.length;
  const finishedTasks = byStatus.finished ?? tasks.filter((task) => task.status === "finished").length;
  const failedTasks = byStatus.failed ?? tasks.filter((task) => task.status === "failed").length;

  return (
    <>
      <PageHead
        title={detail?.purpose || "报告"}
        sub={
          <>
            <span>
              {detail?.product || "—"} · {detail?.submitter || "—"}
            </span>
            <span className="pbe-meta">
              <span className="pbe-meta__sep">·</span>
              <CopyId value={props.jobId} label="job id" keep={20} />
              <span className="pbe-meta__sep">·</span>
              <StatusPill
                tone={detail ? jobStatus(detail.status).tone : "muted"}
                label={detail ? jobStatus(detail.status).label : "读取中"}
              />
              <span className="pbe-meta__sep">·</span>
              <CopyId value={linkFor} label="报告链接" keep={30} />
            </span>
          </>
        }
        actions={
          <>
            <Button onClick={props.onBack}>返回列表</Button>
            <Segmented
              value={props.sensitivity}
              onChange={(value: any) => props.onSensitivity(value as Sensitivity)}
              options={[
                { value: "shared", label: "shared" },
                { value: "full", label: "完整版" },
              ]}
            />
          </>
        }
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

      {detail?.error ? (
        <Alert
          type="warning"
          showIcon
          message="这次运行没有跑完"
          description={detail.error}
          style={{ marginBottom: "var(--spacer-16)" }}
        />
      ) : null}

      <Panel pad={false}>
        <div style={{ padding: "var(--spacer-20) var(--spacer-24)" }}>
          <div className="pbe-scoreboard">
            <Cell label="总分" value={mean === null ? "—" : fixed(mean)} note={detail?.score ? `计分 ${scoreCount} 题` : undefined} />
            <Cell
              label="完成"
              value={`${finishedTasks} / ${totalTasks}`}
              note={failedTasks ? `${failedTasks} 失败` : "无失败"}
            />
            <Cell label="分数区间" value={high === null ? "—" : `${fixed(low)} – ${fixed(high)}`} note={`${scores.length} 题计分`} />
            <Cell label="耗时" value={duration(secondsBetween(detail))} note={stamp(detail?.started_at)} />
          </div>
        </div>
      </Panel>

      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          {
            key: "overview",
            label: "总览",
            children: (
              <div className="pbe-grid" style={{ marginTop: "var(--spacer-16)" }}>
                <Panel>
                  <SectionTitle>总分与状态分布</SectionTitle>
                  <div style={{ display: "flex", alignItems: "center", gap: "var(--spacer-24)" }}>
                    <Progress
                      type="dashboard"
                      size={132}
                      percent={mean === null ? 0 : Math.round(mean * 100)}
                      format={() => (mean === null ? "—" : fixed(mean))}
                    />
                    <div className="pbe-rows" style={{ flex: 1 }}>
                      <Row label="计分题" value={String(progress.scored ?? scores.length)} />
                      <Row label="没计分的" value={String(Math.max(0, totalTasks - (progress.scored ?? 0)))} />
                      <Row
                        label="最高 / 最低"
                        value={high === null ? "—" : `${fixed(high)} / ${fixed(low)}`}
                      />
                      <Row label="生成时间" value={stamp(detail?.generated_at)} />
                    </div>
                  </div>
                  {statusRows.length ? (
                    <div className="pbe-rows" style={{ marginTop: "var(--spacer-12)" }}>
                      {statusRows.map(([key, value]) => (
                        <Row key={key} label={jobStatus(key).label} value={`${value} 题`} />
                      ))}
                    </div>
                  ) : null}
                </Panel>

                <Panel>
                  <SectionTitle>切片</SectionTitle>
                  <Slices title="能力" data={detail?.slices?.capability} />
                  <Slices title="场景" data={detail?.slices?.scenario} />
                  <Slices title="复杂度" data={detail?.slices?.complexity} />
                </Panel>

                <Panel>
                  <SectionTitle>数据来源</SectionTitle>
                  {(detail?.sources ?? []).length ? (
                    <div className="pbe-rows">
                      {detail!.sources.map((source) => (
                        <Row
                          key={source.dataset_id}
                          label={String(source.name || source.dataset_id)}
                          value={`${source.task_count} 题`}
                        />
                      ))}
                    </div>
                  ) : (
                    <EmptyHint>这次运行没有记录数据来源</EmptyHint>
                  )}
                </Panel>

                <Panel>
                  <SectionTitle>运行配置</SectionTitle>
                  <div className="pbe-facts">
                    <Fact label="ACP 地址" value={<span className="pbe-mono">{detail?.acp_url}</span>} />
                    <Fact
                      label="窗口"
                      value={
                        detail
                          ? `${detail.window.kind}${detail.window.start ? ` · ${stamp(detail.window.start)}` : ""}`
                          : "—"
                      }
                    />
                    <Fact label="提交时间" value={stamp(detail?.created_at)} />
                    <Fact label="结束时间" value={stamp(detail?.finished_at)} />
                  </div>
                </Panel>

                <Panel spanAll>
                  <SectionTitle>环境指纹</SectionTitle>
                  <div className="pbe-block" style={{ maxHeight: 240 }}>
                    {json(detail?.env_fingerprint ?? "这次提交没有带指纹")}
                  </div>
                </Panel>
              </div>
            ),
          },
          {
            key: "tasks",
            label: `题目 ${tasks.length}`,
            children: (
              <div style={{ marginTop: "var(--spacer-16)" }}>
                <div className="pbe-toolbar">
                  <span className="pbe-toolbar__label">筛选</span>
                  <Segmented
                    value={filter}
                    onChange={(value: any) => setFilter(value as TaskFilter)}
                    options={[
                      { value: "all", label: `全部 ${tasks.length}` },
                      { value: "bad", label: `异常 ${tasks.filter(isBad).length}` },
                      { value: "low", label: `低分 ${tasks.filter(lowScore).length}` },
                      { value: "unscored", label: "未计分" },
                    ]}
                  />
                  <div className="pbe-toolbar__right">
                    <Input.Search
                      allowClear
                      placeholder="题目名 / task id / trace id"
                      style={{ width: 260 }}
                      value={search}
                      onChange={(event: any) => setSearch(event.target.value)}
                    />
                  </div>
                </div>
                <div className="pbe-table-wrap">
                  <Table
                    className="pbe-table"
                    rowKey={(task: TaskEntry) => `${task.task_id}-${task.attempt}`}
                    size="middle"
                    loading={loading}
                    dataSource={shown}
                    pagination={false}
                    onRow={(task: TaskEntry) => ({ onClick: () => setOpenTask(task) })}
                    locale={{ emptyText: <EmptyHint>没有符合筛选的题目</EmptyHint> }}
                    columns={taskColumns()}
                  />
                  <div className="pbe-table__foot">
                    <span>共 {shown.length} 条</span>
                    <span>点一行看题干、判据与轨迹</span>
                  </div>
                </div>
              </div>
            ),
          },
          {
            key: "export",
            label: "导出",
            children: (
              <div className="pbe-grid" style={{ marginTop: "var(--spacer-16)" }}>
                <Panel>
                  <SectionTitle>生成报告</SectionTitle>
                  <Radio.Group
                    value={format}
                    onChange={(event: any) => setFormat(event.target.value)}
                    style={{ display: "flex", flexDirection: "column", gap: "var(--spacer-12)" }}
                  >
                    {FORMATS.map((item) => {
                      const disabled = Boolean(item.fullOnly) && props.sensitivity !== "full";
                      return (
                        <Radio key={item.value} value={item.value} disabled={disabled}>
                          <span>{item.label}</span>
                          <span className="pbe-cell-sub" style={{ marginLeft: 8 }}>
                            {disabled ? `${item.hint}（需要完整版）` : item.hint}
                          </span>
                        </Radio>
                      );
                    })}
                  </Radio.Group>
                  <div style={{ marginTop: "var(--spacer-20)", display: "flex", gap: "var(--spacer-8)" }}>
                    <Button type="primary" loading={exporting} onClick={generate}>
                      生成并打开
                    </Button>
                    <Tooltip title="submissions/*.json 的形状，排行榜直接吃得下">
                      <Button onClick={() => void saveSubmissions(props.jobId)}>
                        另存 submissions JSON
                      </Button>
                    </Tooltip>
                  </div>
                </Panel>

                <Panel>
                  <SectionTitle>刚刚生成的</SectionTitle>
                  {lastExport ? (
                    <div className="pbe-facts">
                      <Fact label="文件" value={<span className="pbe-mono">{lastExport.filename}</span>} />
                      <Fact label="大小" value={bytes(lastExport.size)} />
                      <Fact
                        label="链接"
                        value={
                          <Button type="link" style={{ padding: 0 }} onClick={() => window.open(lastExport.url, "_blank", "noopener")}>
                            再打开一次
                          </Button>
                        }
                      />
                      <Fact
                        label="保存到本地"
                        value={
                          <Button
                            type="link"
                            style={{ padding: 0 }}
                            onClick={() => {
                              void downloadToFile(props.jobId, format, props.sensitivity, lastExport.filename);
                            }}
                          >
                            通过代理下载
                          </Button>
                        }
                      />
                    </div>
                  ) : (
                    <EmptyHint>还没有生成。选一种格式，点左边「生成并打开」。</EmptyHint>
                  )}
                  {props.sensitivity !== "full" ? (
                    <div className="pbe-cell-sub" style={{ marginTop: "var(--spacer-12)" }}>
                      当前是 shared 档：判分依据、工作目录、产物下载链接不在报告里。切到「完整版」再导出。
                    </div>
                  ) : null}
                </Panel>
              </div>
            ),
          },
        ]}
      />

      {openTask ? (
        <TaskDialog
          jobId={props.jobId}
          task={openTask}
          sensitivity={props.sensitivity}
          onClose={() => setOpenTask(null)}
        />
      ) : null}
    </>
  );
}

/** The leaderboard shape, for the case where the report is not the deliverable. */
async function saveSubmissions(jobId: string): Promise<void> {
  const payload = await api.results(jobId);
  saveBlob(
    new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
    `${jobId}.json`,
  );
}

async function downloadToFile(
  jobId: string,
  format: ReportFormat,
  sensitivity: Sensitivity,
  filename: string,
): Promise<void> {
  await download(`/v1/reports/${jobId}/${encodeURIComponent(filename)}`, filename);
}

function Cell(props: { label: string; value: unknown; note?: unknown }): unknown {
  return (
    <div className="pbe-scoreboard__cell">
      <div className="pbe-scoreboard__label">{props.label}</div>
      <div className="pbe-scoreboard__value">{props.value}</div>
      {props.note ? <div className="pbe-scoreboard__label">{props.note}</div> : null}
    </div>
  );
}

function Row(props: { label: string; value: unknown }): unknown {
  return (
    <div className="pbe-row">
      <span className="pbe-row__grow">{props.label}</span>
      <span className="pbe-mono">{props.value}</span>
    </div>
  );
}

function Slices(props: { title: string; data?: Record<string, number> }): unknown {
  const entries = Object.entries(props.data ?? {});
  if (!entries.length) {
    return <div className="pbe-cell-sub">没有{props.title}切片</div>;
  }
  return (
    <div style={{ marginBottom: "var(--spacer-12)" }}>
      <div className="pbe-cell-sub" style={{ marginBottom: "var(--spacer-8)" }}>
        {props.title}
      </div>
      {entries.map(([name, score]) => (
        <div key={name} style={{ marginBottom: "var(--spacer-8)" }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <span className="pbe-cell-sub">{name}</span>
            <span className="pbe-mono">{fixed(score)}</span>
          </div>
          <Progress percent={Math.round(Number(score) * 100)} size="small" showInfo={false} />
        </div>
      ))}
    </div>
  );
}

function taskColumns(): any[] {
  return [
    {
      title: "题目",
      dataIndex: "name",
      render: (_: unknown, task: TaskEntry) => (
        <div>
          <div className="pbe-cell-title">{task.name || task.task_id}</div>
          <div className="pbe-cell-sub">
            {task.task_id}
            {task.attempt > 1 ? ` · 第 ${task.attempt} 次尝试` : ""}
          </div>
        </div>
      ),
    },
    {
      title: "标签",
      dataIndex: "labels",
      width: 220,
      render: (_: unknown, task: TaskEntry) => (
        <span className="pbe-cell-sub">{String(task.labels?.scenario ?? "—")}</span>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 140,
      render: (_: unknown, task: TaskEntry) => {
        const meta = taskStatus(task.status, task.failure_reason);
        return <StatusPill tone={meta.tone} label={meta.label} />;
      },
    },
    {
      title: "分数",
      dataIndex: "score",
      width: 84,
      render: (_: unknown, task: TaskEntry) => (
        <Figure value={typeof task.score === "number" ? fixed(task.score) : "—"} />
      ),
    },
    {
      title: "耗时",
      dataIndex: "duration_s",
      width: 96,
      render: (_: unknown, task: TaskEntry) => (
        <span className="pbe-cell-sub">{duration(task.duration_s)}</span>
      ),
    },
    {
      title: "trace_id",
      dataIndex: "trace_id",
      width: 148,
      render: (_: unknown, task: TaskEntry) => <CopyId value={task.trace_id} label="trace_id" keep={12} />,
    },
  ];
}

/**
 * One task, in the order a reader argues with it: what was asked, what ran,
 * what was graded, what came out, and then the raw timeline.
 */
function TaskDialog(props: {
  jobId: string;
  task: TaskEntry;
  sensitivity: Sensitivity;
  onClose: () => void;
}): unknown {
  const [page, setPage] = useState<TranscriptPage | null>(null);
  const [cursor, setCursor] = useState(0);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<TaskEntry>(props.task);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .taskDetail(props.jobId, props.task.task_id, props.sensitivity, props.task.attempt)
      .then((next) => {
        if (!alive) return;
        setDetail(next);
        setPage(next.transcript);
        setCursor(next.transcript.cursor);
        setError("");
      })
      .catch((err) => {
        if (!alive) return;
        setError(describeError(err).message);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [props.jobId, props.task.task_id, props.task.attempt, props.sensitivity]);

  async function goPage(next: number): Promise<void> {
    setLoading(true);
    try {
      const pageOut = await api.transcript(props.jobId, props.task.task_id, props.task.attempt, next);
      setPage(pageOut);
      setCursor(pageOut.cursor);
    } catch (err) {
      setError(describeError(err).message);
    } finally {
      setLoading(false);
    }
  }

  const breakdown = Object.entries(detail.automated_breakdown ?? {});
  const meta = taskStatus(detail.status, detail.failure_reason);

  return (
    <Modal
      open
      width={1040}
      onCancel={props.onClose}
      footer={
        <Button onClick={props.onClose}>关闭</Button>
      }
      title={
        <div style={{ display: "flex", alignItems: "center", gap: "var(--spacer-12)" }}>
          <span>{detail.name || detail.task_id}</span>
          <StatusPill tone={meta.tone} label={meta.label} />
          <span className="pbe-cell-sub">
            {typeof detail.score === "number" ? `得分 ${fixed(detail.score)}` : "未计分"}
          </span>
        </div>
      }
    >
      {error ? <Alert type="error" showIcon message="读不到这一题" description={error} /> : null}

      <SectionTitle>题干</SectionTitle>
      <pre className="pbe-block pbe-prompt">{detail.prompt || "（这次运行没有记录题干）"}</pre>

      <div style={{ height: "var(--spacer-20)" }} />
      <SectionTitle>这次执行</SectionTitle>
      <div className="pbe-facts">
        <Fact label="判分方式" value={detail.grading_type || "—"} />
        <Fact label="耗时" value={duration(detail.duration_s)} />
        <Fact label="协议写回 / 带外" value={`${detail.protocol_written} / ${detail.out_of_band_count}`} />
        <Fact
          label="自报模型"
          value={(detail.subject_model_reported ?? []).join("、") || "—"}
        />
        <Fact label="解析自" value={(detail.resolved_from ?? []).join("、") || "—"} />
        <Fact label="trace_id" value={<CopyId value={detail.trace_id} label="trace_id" keep={16} />} />
        <Fact label="session_id" value={<CopyId value={detail.session_id} label="session_id" keep={24} />} />
      </div>

      {breakdown.length ? (
        <>
          <div style={{ height: "var(--spacer-20)" }} />
          <SectionTitle>判据逐项</SectionTitle>
          <div className="pbe-rows">
            {breakdown.map(([name, value]) => (
              <div className="pbe-row" key={name}>
                <span className="pbe-row__grow">{name}</span>
                <StatusPill
                  tone={Number(value) >= 1 ? "ok" : Number(value) > 0 ? "warn" : "err"}
                  label={fixed(value)}
                />
              </div>
            ))}
          </div>
        </>
      ) : null}

      <div style={{ height: "var(--spacer-20)" }} />
      <SectionTitle>产物</SectionTitle>
      {detail.artifacts.length ? (
        <div className="pbe-rows">
          {detail.artifacts.map((artifact) => (
            <div className="pbe-row" key={artifact.path}>
              <span className="pbe-row__grow pbe-mono">{artifact.path}</span>
              <span className="pbe-cell-sub">{bytes(artifact.size)}</span>
              <Tooltip title={artifact.sha256}>
                <span className="pbe-cell-sub pbe-mono">{artifact.sha256.slice(0, 12)}</span>
              </Tooltip>
              {props.sensitivity === "full" ? (
                <Button
                  type="link"
                  size="small"
                  style={{ padding: 0 }}
                  onClick={() => {
                    void download(
                      `/v1/jobs/${props.jobId}/tasks/${detail.task_id}/attempts/${detail.attempt}/artifacts?path=${encodeURIComponent(artifact.path)}`,
                      artifact.path.split("/").pop() || "artifact",
                    );
                  }}
                >
                  下载
                </Button>
              ) : null}
            </div>
          ))}
        </div>
      ) : (
        <EmptyHint>这次没有产物</EmptyHint>
      )}

      {detail.rubric_excerpt || detail.judge_notes ? (
        <>
          <div style={{ height: "var(--spacer-20)" }} />
          <SectionTitle>评分依据（完整版）</SectionTitle>
          {detail.rubric_excerpt ? <pre className="pbe-block">{detail.rubric_excerpt}</pre> : null}
          {detail.judge_notes ? (
            <pre className="pbe-block" style={{ marginTop: "var(--spacer-8)" }}>
              {detail.judge_notes}
            </pre>
          ) : null}
        </>
      ) : null}

      <div style={{ height: "var(--spacer-20)" }} />
      <SectionTitle>轨迹</SectionTitle>
      <div className="pbe-toolbar">
        <span className="pbe-toolbar__label">
          {page ? `${page.cursor + 1}–${page.cursor + page.events.length} / ${page.total_events} 步` : "读取中"}
          {page && page.damaged_events ? ` · ${page.damaged_events} 条损坏` : ""}
        </span>
        <div className="pbe-toolbar__right">
          <Button size="small" disabled={!page || page.cursor === 0 || loading} onClick={() => goPage(0)}>
            回到开头
          </Button>
          <Button size="small" disabled={!page || !page.next_cursor || loading} onClick={() => page && page.next_cursor !== null && goPage(page.next_cursor)}>
            下一页
          </Button>
        </div>
      </div>
      <div className="pbe-timeline">
        {(page?.events ?? []).map((event, index) => (
          <TimelineRow key={`${cursor}-${index}`} event={event} />
        ))}
        {page && !page.events.length ? <EmptyHint>没有轨迹事件</EmptyHint> : null}
      </div>
    </Modal>
  );
}

const KIND: Record<string, string> = {
  agent_message_chunk: "输出",
  agent_thought_chunk: "思考",
  tool_call: "调用",
  tool_call_update: "结果",
  plan: "计划",
  plan_update: "计划",
  user_message_chunk: "输入",
  available_commands_update: "命令",
  usage_update: "用量",
  current_mode_update: "模式",
  session_info_update: "会话",
  config_option_update: "配置",
};

function TimelineRow(props: { event: TranscriptEvent }): unknown {
  const event = props.event;
  const label = KIND[event.kind] ?? event.kind;
  const args = event.args && Object.keys(event.args).length ? Object.keys(event.args).join("、") : "";
  const summary =
    event.tool || args || (event.chars ? `${event.chars} 字符` : "") || (event.result_chars ? `${event.result_chars} 字符` : "");
  return (
    <div className="pbe-timeline__item">
      <span className="pbe-timeline__at">{String(event.at).replace("T", " ").slice(11, 19)}</span>
      <span>
        <StatusPill tone={event.status === "completed" ? "ok" : "muted"} label={label} />
      </span>
      <span className="pbe-cell-sub" style={{ whiteSpace: "normal" }}>
        {summary || "—"}
      </span>
    </div>
  );
}

function secondsBetween(detail: JobDetail | null): number | null {
  if (!detail?.started_at || !detail.finished_at) return null;
  const start = Date.parse(detail.started_at);
  const end = Date.parse(detail.finished_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, (end - start) / 1000);
}
