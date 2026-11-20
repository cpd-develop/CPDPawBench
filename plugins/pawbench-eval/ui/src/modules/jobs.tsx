/**
 * 评测 — the landing page.
 *
 * The list is the product: one row per submission, with the three numbers a
 * reader actually opens this page for (how far along it is, what it scored, and
 * whether it is still mine to touch).  Everything else — the form, the report —
 * is one click away and does not share the page with it.
 *
 * Two things are deliberate about the numbers here:
 *
 * - ``score`` is ``null`` when nothing was scorable, and that renders as ``—``,
 *   not ``0``.  A run where every task failed measured nothing; averaging it in
 *   as a zero would make the team's trend line depend on how many broken runs
 *   happened that week.
 * - The progress bar counts *graded* tasks, not "not queued" ones.  A failure
 *   is not progress towards a score.
 */

import { Button, Input, Pagination, Popconfirm, Progress, Segmented, Table, Tooltip } from "../host/antd";
import { icons } from "../host/sdk";
import { useMemo, useState } from "../host/react";
import { api, JobItem } from "../api";
import { describeError } from "../host/sdk";
import {
  EmptyHint,
  PageHead,
  StatusPill,
  duration,
  fixed,
  jobStatus,
  stamp,
} from "../ui/primitives";
import { useFeedback } from "../ui/feedback";

const PAGE_SIZE = 20;

const ORDERABLE = new Set(["queued", "scheduled"]);
const FINISHED = new Set(["finished", "failed", "canceled"]);

type Filter = "all" | "running" | "waiting" | "done";

/** 进度按已判分算，不是按"不在队列里"算——后者会把失败当成完成。 */
function progressOf(job: JobItem): { finished: number; total: number; ratio: number } {
  const total = Math.max(0, Number(job.task_count) || 0);
  const finished = Math.max(0, Number(job.tasks_finished) || 0);
  return { finished, total, ratio: total ? Math.min(1, finished / total) : 0 };
}

/** A score needs a colour rule, and the rule needs to be one rule. */
function scoreTone(score: number | null): string {
  if (score === null || score === undefined) return "";
  if (score >= 0.8) return " pbe-score--ok";
  if (score < 0.5) return " pbe-score--low";
  return "";
}

/**
 * What the list is ordered by, and why it is two rules rather than one.
 *
 * The service hands rows out by ``queue_pos``, which is submission order — the
 * order the queue runs in, and the order ``↑ ↓`` moves things inside.  Correct
 * for a queue, wrong for a page: the run somebody just submitted lands at the
 * bottom, ten rows below a week of history.
 *
 * So: live work first (running, then waiting in queue order, because that is
 * the order it will actually run in), and the ended rows newest first, because
 * those are read and not executed.  The waiting bucket keeps the service's
 * order verbatim, so the arrows never lie about which row is next.
 */
const RANK_LIVE = 0;
const RANK_WAITING = 1;
const RANK_ENDED = 2;

function rankOf(job: JobItem): number {
  if (job.status === "running") return RANK_LIVE;
  if (ORDERABLE.has(job.status)) return RANK_WAITING;
  return RANK_ENDED;
}

function byReadingOrder(a: JobItem, b: JobItem): number {
  const rank = rankOf(a) - rankOf(b);
  if (rank !== 0) return rank;
  if (rankOf(a) !== RANK_ENDED) {
    return (Number(a.queue_pos) || 0) - (Number(b.queue_pos) || 0);
  }
  return String(b.created_at).localeCompare(String(a.created_at));
}

export function JobsModule(props: {
  jobs: JobItem[];
  loading: boolean;
  subject: string;
  onOpen: (jobId: string) => void;
  onRefresh: () => void;
  onNew: () => void;
}): unknown {
  const feedback = useFeedback();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState("");

  const stats = useMemo(() => {
    const running = props.jobs.filter((job) => job.status === "running").length;
    const waiting = props.jobs.filter((job) => ORDERABLE.has(job.status)).length;
    const done = props.jobs.filter((job) => job.status === "finished").length;
    const scored = props.jobs
      .map((job) => job.score)
      .filter((score): score is number => typeof score === "number");
    const mean = scored.length ? scored.reduce((sum, value) => sum + value, 0) / scored.length : null;
    return { running, waiting, done, mean, scored: scored.length };
  }, [props.jobs]);

  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return props.jobs
      .filter((job) => {
        if (filter === "running" && job.status !== "running") return false;
        if (filter === "waiting" && !ORDERABLE.has(job.status)) return false;
        if (filter === "done" && !FINISHED.has(job.status)) return false;
        if (!needle) return true;
        return [job.purpose, job.product, job.job_id, job.submitter, job.acp_url]
          .join(" ")
          .toLowerCase()
          .includes(needle);
      })
      .sort(byReadingOrder);
  }, [props.jobs, filter, search]);

  const paged = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return visible.slice(start, start + PAGE_SIZE);
  }, [visible, page]);

  const canReorder = (job: JobItem): boolean =>
    ORDERABLE.has(job.status) && (!props.subject || job.submitter === props.subject);

  async function reorder(job: JobItem, target: string): Promise<void> {
    setBusy(job.job_id);
    try {
      await api.reorder(job.job_id, { target });
      props.onRefresh();
    } catch (error) {
      const info = describeError(error);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy("");
    }
  }

  async function cancel(job: JobItem): Promise<void> {
    setBusy(job.job_id);
    try {
      await api.cancel(job.job_id, "dashboard");
      feedback.message.success("已取消");
      props.onRefresh();
    } catch (error) {
      const info = describeError(error);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy("");
    }
  }

  const icon = icons() as Record<string, any>;
  const Play = icon.PlayCircleOutlined;
  const Clock = icon.ClockCircleOutlined;
  const Check = icon.CheckCircleOutlined;
  const Gauge = icon.DashboardOutlined;

  const columns = [
    {
      title: "状态",
      dataIndex: "status",
      width: 124,
      render: (_: unknown, job: JobItem) => {
        const meta = jobStatus(job.status);
        return (
          <div>
            <StatusPill tone={meta.tone} label={meta.label} />
            {ORDERABLE.has(job.status) && job.queue_pos !== null ? (
              <div className="pbe-cell-sub">队列 #{Number(job.queue_pos).toFixed(1)}</div>
            ) : null}
          </div>
        );
      },
    },
    {
      title: "评测",
      dataIndex: "purpose",
      render: (_: unknown, job: JobItem) => (
        <div style={{ minWidth: 0 }}>
          <div className="pbe-cell-title">{job.purpose || "（未命名）"}</div>
          <div className="pbe-cell-sub">
            {job.product || "—"} · {job.job_id}
          </div>
        </div>
      ),
    },
    {
      title: "题目",
      dataIndex: "task_count",
      width: 156,
      render: (_: unknown, job: JobItem) => {
        const progress = progressOf(job);
        return (
          <div>
            <div className="pbe-cell-sub" style={{ marginBottom: 4 }}>
              <span className="pbe-mono">
                {progress.finished} / {progress.total || "?"}
              </span>
              {job.tasks_failed ? ` · ${job.tasks_failed} 失败` : ""}
            </div>
            <Progress
              percent={Math.round(progress.ratio * 100)}
              size="small"
              showInfo={false}
              status={job.tasks_failed ? "exception" : job.status === "running" ? "active" : "normal"}
            />
          </div>
        );
      },
    },
    {
      title: "分数",
      dataIndex: "score",
      width: 92,
      render: (_: unknown, job: JobItem) => (
        <span className={`pbe-figure${scoreTone(job.score)}`}>
          {job.score === null || job.score === undefined ? "—" : fixed(job.score)}
        </span>
      ),
    },
    {
      title: "提交人",
      dataIndex: "submitter",
      width: 104,
      render: (value: string) => <span className="pbe-cell-sub">{value || "—"}</span>,
    },
    {
      title: "时间",
      dataIndex: "created_at",
      width: 156,
      render: (_: unknown, job: JobItem) => (
        <div>
          <div className="pbe-cell-sub">{stamp(job.created_at)}</div>
          {job.finished_at ? (
            <div className="pbe-cell-sub">耗时 {duration(secondsBetween(job))}</div>
          ) : job.not_before ? (
            <div className="pbe-cell-sub">起跑 {stamp(job.not_before)}</div>
          ) : null}
        </div>
      ),
    },
    {
      title: "操作",
      dataIndex: "job_id",
      width: 150,
      render: (_: unknown, job: JobItem) => {
        const disabled = !canReorder(job) || busy === job.job_id;
        const why = !ORDERABLE.has(job.status)
          ? "已经不在队列里了"
          : props.subject && job.submitter !== props.subject
            ? "只能调自己提交的作业"
            : "";
        return (
          <div style={{ display: "flex", gap: 4 }} onClick={(event: any) => event.stopPropagation()}>
            <Tooltip title={why || "上移"}>
              <Button
                size="small"
                type="text"
                aria-label="上移"
                disabled={disabled}
                onClick={() => reorder(job, "up")}
              >
                ↑
              </Button>
            </Tooltip>
            <Tooltip title={why || "下移"}>
              <Button
                size="small"
                type="text"
                aria-label="下移"
                disabled={disabled}
                onClick={() => reorder(job, "down")}
              >
                ↓
              </Button>
            </Tooltip>
            <Tooltip title="打开报告">
              <Button size="small" type="text" aria-label="打开报告" onClick={() => props.onOpen(job.job_id)}>
                报告
              </Button>
            </Tooltip>
            {ORDERABLE.has(job.status) || job.status === "running" ? (
              <Popconfirm
                title="取消这次评测？"
                description={
                  job.status === "running" ? "运行中的会话会被停掉，已跑完的题保留。" : "排队中的作业会被移出队列。"
                }
                okText="取消作业"
                cancelText="先不取消"
                onConfirm={() => cancel(job)}
              >
                <Tooltip title="取消">
                  <Button size="small" type="text" danger aria-label="取消" disabled={disabled}>
                    取消
                  </Button>
                </Tooltip>
              </Popconfirm>
            ) : null}
          </div>
        );
      },
    },
  ];

  return (
    <>
      <PageHead
        title="评测"
        sub="一次提交一行。点任意一行打开报告；行内能看到题目进度和平均分。"
        actions={
          <>
            <Tooltip title="重新拉取列表">
              <Button aria-label="刷新" onClick={props.onRefresh} loading={props.loading}>
                刷新
              </Button>
            </Tooltip>
            <Button type="primary" onClick={props.onNew}>
              新建评测
            </Button>
          </>
        }
      />

      <div className="pbe-metrics">
        <MetricItem
          icon={Play ? <Play /> : null}
          title="运行中"
          figure={stats.running}
          note={stats.running ? "占着并发槽" : "当前空闲"}
        />
        <MetricItem
          icon={Clock ? <Clock /> : null}
          title="等待中"
          figure={stats.waiting}
          note={stats.waiting ? "含排队与待起跑" : "队列为空"}
        />
        <MetricItem
          icon={Gauge ? <Gauge /> : null}
          title="已完成"
          figure={stats.done}
          note={`平均分 ${stats.mean === null ? "—" : fixed(stats.mean)}${stats.scored ? ` · ${stats.scored} 次计分` : ""}`}
        />
      </div>

      <div className="pbe-toolbar">
        <span className="pbe-toolbar__label">筛选</span>
        <Segmented
          value={filter}
          onChange={(value: any) => {
            setFilter(value as Filter);
            setPage(1);
          }}
          options={[
            { value: "all", label: `全部 ${props.jobs.length}` },
            { value: "running", label: "运行中" },
            { value: "waiting", label: "等待中" },
            { value: "done", label: "已结束" },
          ]}
        />
        <div className="pbe-toolbar__right">
          <Input.Search
            allowClear
            placeholder="按目的、产品、提交人、job id 搜索"
            style={{ width: 260 }}
            value={search}
            onChange={(event: any) => {
              setSearch(event.target.value);
              setPage(1);
            }}
          />
        </div>
      </div>

      <div className="pbe-table-wrap">
        <Table
          className="pbe-table"
          rowKey="job_id"
          size="middle"
          loading={props.loading && !props.jobs.length}
          columns={columns as any}
          dataSource={paged}
          pagination={false}
          onRow={(job: JobItem) => ({ onClick: () => props.onOpen(job.job_id) })}
          locale={{
            emptyText: (
              <EmptyHint>
                还没有评测。点右上角「新建评测」提交一次，或检查「配置」里的服务地址。
              </EmptyHint>
            ),
          }}
        />
        <div className="pbe-table__foot">
          <span>共 {visible.length} 条</span>
          <Pagination
            size="small"
            current={page}
            pageSize={PAGE_SIZE}
            total={visible.length}
            showSizeChanger={false}
            onChange={(next: number) => setPage(next)}
            hideOnSinglePage
          />
        </div>
      </div>

      <div className="pbe-toolbar" style={{ marginTop: "var(--spacer-16)" }}>
        <span className="pbe-toolbar__label">
          「等待中」才可调序；「已结束」才有报告。分数显示「—」表示没有可计分的题，不等于 0 分。
        </span>
        <div className="pbe-toolbar__right">
          <Check style={{ color: "var(--status-success-default)" }} />
          <span className="pbe-toolbar__label">列表会在运行中自动刷新</span>
        </div>
      </div>
    </>
  );
}

function MetricItem(props: {
  icon: unknown;
  title: string;
  figure: unknown;
  note: string;
}): unknown {
  return (
    <div className="pbe-panel pbe-metric">
      <span className="pbe-tile" aria-hidden="true">
        {props.icon}
      </span>
      <div className="pbe-metric__body">
        <div className="pbe-metric__title">{props.title}</div>
        <div className="pbe-metric__desc">
          <span className="pbe-figure">{props.figure}</span>
          <span>{props.note}</span>
        </div>
      </div>
    </div>
  );
}

function secondsBetween(job: JobItem): number | null {
  if (!job.started_at || !job.finished_at) return null;
  const start = Date.parse(job.started_at);
  const end = Date.parse(job.finished_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, (end - start) / 1000);
}
