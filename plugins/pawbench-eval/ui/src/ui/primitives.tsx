/**
 * Small pieces that make the modules read like one page.
 *
 * Every one of them exists because the same shape was needed three times: a
 * status that has one colour in one place, an id that has to be copyable, a
 * field whose label sits left of its control.  Keeping them here is what stops
 * the modules from each inventing their own idea of "green".
 */

import { Tooltip } from "../host/antd";
import { useState } from "../host/react";
import { copyText } from "../host/sdk";
import { useFeedback } from "./feedback";

export interface PillTone {
  tone: "ok" | "warn" | "err" | "info" | "muted";
  label: string;
}

/** One place where a service status becomes a tone and a word. */
export function jobStatus(status: string): PillTone {
  switch (status) {
    case "running":
      return { tone: "info", label: "运行中" };
    case "queued":
      return { tone: "warn", label: "已排队" };
    case "scheduled":
      return { tone: "warn", label: "待起跑" };
    case "finished":
      return { tone: "ok", label: "已完成" };
    case "failed":
      return { tone: "err", label: "失败" };
    case "canceled":
      return { tone: "muted", label: "已取消" };
    case "new":
      return { tone: "muted", label: "已登记" };
    default:
      return { tone: "muted", label: status || "未知" };
  }
}

/**
 * A task's status is the job's, except where the attempt is what matters:
 * a skipped task never ran, and a task with no artifacts was graded against
 * nothing.  Both are failures the reader needs to tell apart from a low score.
 */
export function taskStatus(status: string, failureReason?: string | null): PillTone {
  if (failureReason) {
    return { tone: "err", label: failureReason };
  }
  switch (status) {
    case "skipped":
      return { tone: "err", label: "跳过" };
    case "no_artifacts":
      return { tone: "err", label: "无产物" };
    case "missing":
      return { tone: "err", label: "缺失" };
    default:
      return jobStatus(status);
  }
}

export function StatusPill(props: { tone: PillTone["tone"]; label: string }): unknown {
  return (
    <span className={`pbe-pill pbe-pill--${props.tone}`}>
      <span className="pbe-pill__dot" aria-hidden="true" />
      {props.label}
    </span>
  );
}

export function PageHead(props: {
  title: string;
  sub?: unknown;
  actions?: unknown;
}): unknown {
  return (
    <div className="pbe-head">
      <div className="pbe-head__text">
        <h1 className="pbe-head__title">{props.title}</h1>
        {props.sub ? <div className="pbe-head__sub">{props.sub}</div> : null}
      </div>
      {props.actions ? <div className="pbe-head__actions">{props.actions}</div> : null}
    </div>
  );
}

export function Panel(props: {
  children: unknown;
  pad?: boolean;
  link?: boolean;
  spanAll?: boolean;
  className?: string;
  onClick?: () => void;
}): unknown {
  const classes = ["pbe-panel"];
  if (props.pad !== false) classes.push("pbe-panel--pad");
  if (props.link) classes.push("pbe-panel--link");
  if (props.spanAll) classes.push("pbe-span-all");
  if (props.className) classes.push(props.className);
  return (
    <div className={classes.join(" ")} onClick={props.onClick}>
      {props.children}
    </div>
  );
}

export function Tile(props: { children: unknown }): unknown {
  return (
    <span className="pbe-tile" aria-hidden="true">
      {props.children}
    </span>
  );
}

/** C2 tier: a compact metric — 72px, 44px tile, one figure, one note. */
export function MetricCard(props: {
  icon: unknown;
  title: string;
  figure: unknown;
  note: string;
}): unknown {
  return (
    <div className="pbe-panel pbe-metric">
      <Tile>{props.icon}</Tile>
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

export function Figure(props: { value: unknown }): unknown {
  return <span className="pbe-figure">{props.value}</span>;
}

export function SectionTitle(props: { children: unknown }): unknown {
  return <h2 className="pbe-section-title">{props.children}</h2>;
}

export function Fact(props: { label: string; value: unknown }): unknown {
  return (
    <div>
      <div className="pbe-fact__label">{props.label}</div>
      <div className="pbe-fact__value">{props.value}</div>
    </div>
  );
}

/**
 * An identifier, short enough to read and one click from complete.
 *
 * The truncation is the point: a 32-character handle in a table cell is noise,
 * but the reader who wants it is usually about to paste it into a log search,
 * so the full value has to leave with one click — and be shown outright when
 * the clipboard is unavailable, rather than silently doing nothing.
 */
export function CopyId(props: {
  value: string | null | undefined;
  label?: string;
  keep?: number;
}): unknown {
  const message = useFeedback().message;
  const [copied, setCopied] = useState(false);
  const value = String(props.value ?? "");
  if (!value) return <span className="pbe-cell-sub">—</span>;
  const keep = props.keep ?? 12;
  const short = value.length > keep ? `${value.slice(0, keep)}…` : value;

  async function copy(event: { stopPropagation: () => void }): Promise<void> {
    event.stopPropagation();
    const ok = await copyText(value, props.label ?? "id");
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
      message.success(`已复制${props.label ? ` ${props.label}` : ""}`);
    } else {
      message.info(value);
    }
  }

  return (
    <Tooltip title={copied ? "已复制" : `${props.label ?? "id"}：${value}（点击复制）`}>
      <button type="button" className="pbe-copy" onClick={copy}>
        <span className="pbe-copy__value">{short}</span>
        <span aria-hidden="true">复制</span>
      </button>
    </Tooltip>
  );
}

export function Field(props: {
  label: string;
  hint?: unknown;
  children: unknown;
}): unknown {
  return (
    <div className="pbe-field">
      <label className="pbe-field__label">{props.label}</label>
      <div className="pbe-field__control">
        {props.children}
        {props.hint ? <div className="pbe-field__hint">{props.hint}</div> : null}
      </div>
    </div>
  );
}

export function Fieldset(props: { title: string; children: unknown }): unknown {
  return (
    <div className="pbe-fieldset">
      <div className="pbe-fieldset__title">{props.title}</div>
      {props.children}
    </div>
  );
}

export function EmptyHint(props: { children: unknown }): unknown {
  return <div className="pbe-empty">{props.children}</div>;
}

// ── formatting ─────────────────────────────────────────────────────────────

export function fixed(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}

export function percent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(Number(value) * 100)}%`;
}

export function bytes(value: number): string {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

/** Seconds as something a human reads without doing arithmetic. */
export function duration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const total = Math.max(0, Math.round(Number(seconds)));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

/**
 * A timestamp as the service wrote it.
 *
 * Deliberately not `toLocaleString`: these values are UTC, the reader's zone is
 * not, and a report that quietly shifts a start time by seven hours is exactly
 * the mistake the window picker exists to prevent.
 */
export function stamp(value: string | null | undefined): string {
  if (!value) return "—";
  return String(value).replace("T", " ").replace(/(\.\d+)?\+00:00$/, "").replace(/Z$/, "");
}

export function json(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
