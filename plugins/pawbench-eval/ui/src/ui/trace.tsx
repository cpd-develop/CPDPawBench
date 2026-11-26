/**
 * 轨迹 — one run, read the way it happened.
 *
 * The page it replaces was a table of rows: a time, a kind, and a character
 * count.  It was faithful and unreadable, because a run is not a list of
 * notifications -- it is an agent saying something, reaching for a tool, and
 * getting an answer, again and again.  ACP streams that as twenty chunks and
 * four updates, so the raw page buries the four beats that matter under the
 * twenty that do not.
 *
 * The service folds those notifications into beats before it pages them:
 * adjacent chunks of one voice become one utterance, a tool call and the
 * updates that finish it become one card, a plan becomes a checklist.  What
 * reaches this component is already the thing a person would say happened, in
 * order, on one rail.  Paging by beat means "next" lands on the next thing
 * said, not the next fragment of the same sentence; the raw line cursor never
 * leaves the service.
 *
 * Three rules the drawing follows:
 *
 * - The words are the interface.  Speech is set as prose on the page, not in a
 *   box, because a box per turn turns a conversation into a form.
 * - The list carries bounded previews so hundreds of beats stay cheap.  Opening
 *   one asks the service for that beat's complete text, arguments and result --
 *   no ellipsis, no clipped value, no "… +N chars" left behind.
 * - Nothing is hidden that changes a verdict: a failed call keeps its red, a
 *   truncated preview says it is truncated, and the counts stay next to the
 *   text so "500 chars" and "500 chars, all shown" cannot be confused.
 */

import { Button, Segmented } from "../host/antd";
import { Beat, BeatContent, BeatsPage, BeatFilter, BeatFilters } from "../api";
import { useState } from "../host/react";
import { StatusPill } from "./primitives";

const SIZES = [10, 20, 50];

function clock(at: string): string {
  const text = String(at ?? "");
  return text.includes("T") ? text.slice(11, 19) : text;
}

function num(value: number | undefined): string {
  return Number(value ?? 0).toLocaleString("en-US");
}

/** The full payload when opened, falling back to the preview while it loads. */
export interface Opened {
  content: BeatContent | null;
  loading: boolean;
}

export function Trace(props: {
  jobId: string;
  taskId: string;
  attempt: number;
  page: BeatsPage | null;
  loading: boolean;
  error: string;
  opened: Record<number, Opened>;
  onPage: (page: number, size: number, voice: BeatFilter) => void;
  onOpen: (index: number) => void;
}): unknown {
  const page = props.page;
  const size = page?.size ?? 10;
  const voice = page?.voice ?? "all";
  const beats = page?.beats ?? [];

  function go(next: number): void {
    props.onPage(next, size, voice);
  }

  return (
    <div className="pbe-trace">
      <div className="pbe-trace__bar">
        <Segmented
          size="small"
          value={voice}
          onChange={(value: any) => props.onPage(1, size, value as BeatFilter)}
          options={BeatFilters.map((item) => ({
            value: item.value,
            label: `${item.label} ${num(page?.counts[item.value])}`,
          }))}
        />
        <div className="pbe-trace__nav">
          <span className="pbe-trace__pos">
            {page && page.total_beats
              ? `第 ${num((page.page - 1) * size + 1)}–${num((page.page - 1) * size + beats.length)} 步 · 共 ${num(page.total_beats)} 步`
              : page
                ? "没有可显示的步骤"
                : "读取中"}
            {page && page.damaged_events ? ` · ${num(page.damaged_events)} 行读不出` : ""}
          </span>
          <Segmented
            size="small"
            value={size}
            onChange={(value: any) => props.onPage(1, Number(value), voice)}
            options={SIZES.map((value) => ({ value, label: `${value}/页` }))}
          />
          <Button size="small" disabled={!page || page.page === 1 || props.loading} onClick={() => go(1)}>
            回到开头
          </Button>
          <Button size="small" disabled={!page || page.page <= 1 || props.loading} onClick={() => go(page!.page - 1)}>
            上一页
          </Button>
          <Button
            size="small"
            type="primary"
            ghost
            disabled={!page || page.next_page === null || props.loading}
            onClick={() => page?.next_page !== null && page && go(page.next_page)}
          >
            下一页
          </Button>
        </div>
      </div>

      {props.error ? <div className="pbe-trace__error">{props.error}</div> : null}

      <div className="pbe-trace__scroll" aria-busy={props.loading}>
        {page?.transcript_state === "absent" ? (
          <div className="pbe-trace__quiet">
            这次运行没有留下轨迹。可能是 agent 一句没说就退出了，也可能是轨迹文件在运行后被清理掉了。
          </div>
        ) : page?.transcript_state === "unreadable" ? (
          <div className="pbe-trace__quiet">
            轨迹文件在，但读不出来。{" "}
            <span className="pbe-mono">transcript.jsonl</span> 可能被占用或权限变了。
          </div>
        ) : beats.length === 0 ? (
          <div className="pbe-trace__quiet">
            {page && page.total_beats ? "这一页没有符合筛选的步骤。" : "这次运行没有可显示的步骤。"}
          </div>
        ) : (
          beats.map((beat) => (
            <BeatRow
              key={beat.key}
              beat={beat}
              opened={props.opened[beat.index]}
              onOpen={() => props.onOpen(beat.index)}
            />
          ))
        )}
      </div>

      {page && page.next_page !== null ? (
        <div className="pbe-trace__foot">
          <span className="pbe-trace__pos">
            还有 {num(page.total_beats - (page.page - 1) * size - beats.length)} 步
          </span>
          <Button size="small" onClick={() => page.next_page !== null && go(page.next_page)}>
            继续看下一页
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function BeatRow(props: {
  beat: Beat;
  opened: Opened | undefined;
  onOpen: () => void;
}): unknown {
  const beat = props.beat;
  if (beat.voice === "system") return <SystemRow beat={beat} />;
  if (beat.voice === "tool")
    return <ToolRow beat={beat} opened={props.opened} onOpen={props.onOpen} />;
  if (beat.voice === "plan") return <PlanRow beat={beat} />;
  if (beat.voice === "thought")
    return <ThoughtRow beat={beat} opened={props.opened} onOpen={props.onOpen} />;
  return <SpeechRow beat={beat} opened={props.opened} onOpen={props.onOpen} />;
}

/** The rail: a dot per beat, one line through all of them. */
function Rail(props: { voice: Beat["voice"] }): unknown {
  return (
    <span className={`pbe-beat__rail pbe-beat__rail--${props.voice}`} aria-hidden="true">
      <span className="pbe-beat__dot" />
    </span>
  );
}

function Meta(props: { beat: Beat; extra?: unknown; more?: unknown }): unknown {
  const beat = props.beat;
  return (
    <div className="pbe-beat__meta">
      <span className="pbe-beat__who">{beat.label}</span>
      <span className="pbe-mono">{clock(beat.at)}</span>
      {beat.events > 1 && beat.voice !== "tool" ? <span>{beat.events} 段</span> : null}
      {props.extra}
      {props.more ? <span className="pbe-beat__more-slot">{props.more}</span> : null}
    </div>
  );
}

/**
 * Every beat opens and closes from the same slot on its meta row.  Keeping the
 * control out of the content means "收起" does not drift to the bottom when a
 * full result is long, and all rows share one alignment.
 */
function MoreButton(props: {
  opened: Opened | undefined;
  onOpen: () => void;
  collapsedLabel: string;
}): unknown {
  const loading = Boolean(props.opened?.loading);
  const open = Boolean(props.opened) && !loading;
  const label = loading ? "读取完整内容…" : open ? "收起" : props.collapsedLabel;
  return (
    <button
      type="button"
      className={`pbe-beat__more${open ? " pbe-beat__more--open" : ""}`}
      aria-expanded={open}
      disabled={loading}
      onClick={props.onOpen}
    >
      {label}
    </button>
  );
}

function SpeechRow(props: {
  beat: Beat;
  opened: Opened | undefined;
  onOpen: () => void;
}): unknown {
  const beat = props.beat;
  const open = Boolean(props.opened);
  const full = props.opened?.content;
  const text = open && full ? full.text : beat.text;
  const expandable = Boolean(beat.text_truncated || open);
  return (
    <div className={`pbe-beat pbe-beat--${beat.voice}`}>
      <Rail voice={beat.voice} />
      <div className="pbe-beat__body">
        <Meta
          beat={beat}
          extra={beat.chars ? <span>{num(beat.chars)} 字符</span> : null}
          more={
            expandable ? (
              <MoreButton
                opened={props.opened}
                onOpen={props.onOpen}
                collapsedLabel="展开完整内容"
              />
            ) : null
          }
        />
        {text ? (
          <div className="pbe-speech">{text}</div>
        ) : (
          <div className="pbe-beat__quiet">这一条只有长度，没有正文（{num(beat.chars)} 字符）。</div>
        )}
      </div>
    </div>
  );
}

function ThoughtRow(props: {
  beat: Beat;
  opened: Opened | undefined;
  onOpen: () => void;
}): unknown {
  const beat = props.beat;
  const open = Boolean(props.opened);
  const full = props.opened?.content;
  const text = open && full ? full.text : beat.text;
  return (
    <div className="pbe-beat pbe-beat--thought">
      <Rail voice={beat.voice} />
      <div className="pbe-beat__body">
        <Meta
          beat={beat}
          more={
            <MoreButton
              opened={props.opened}
              onOpen={props.onOpen}
              collapsedLabel={`${beat.text_truncated ? "展开完整内容" : "展开"} · ${num(beat.chars)} 字符`}
            />
          }
        />
        <div className={`pbe-thought${open ? " pbe-thought--open" : ""}`}>
          {text || "（这次运行没有记录思考内容）"}
        </div>
      </div>
    </div>
  );
}

function ToolRow(props: {
  beat: Beat;
  opened: Opened | undefined;
  onOpen: () => void;
}): unknown {
  const beat = props.beat;
  const open = Boolean(props.opened);
  const full = props.opened?.content;
  const sourceArgs = open && full ? full.args : beat.args;
  const args = Object.entries(sourceArgs ?? {}).map(([key, value]) => {
    const lines = String(value).split("\n");
    const long = lines.length > 1 || value.length > 80;
    return {
      key,
      value: String(value),
      // A heredoc collapsed into one nowrap line reads as a run-on sentence.
      // On an opened card the value is already full, so it wraps in full too.
      preview: lines.length > 1 ? `${lines[0]} …（还有 ${lines.length - 1} 行）` : String(value),
      long,
    };
  });
  const shown = open ? args : args.slice(0, 3);
  const hidden = args.length - shown.length;
  const output = open && full ? full.output : beat.output;
  const failed = beat.status === "failed" || beat.status === "error";
  const tone: "ok" | "err" | "warn" = failed ? "err" : beat.status === "completed" ? "ok" : "warn";
  const label = beat.status === "completed" ? "完成" : failed ? "失败" : beat.status || "进行中";
  const clipped =
    args.some((arg) => arg.long) || output.split("\n").length > 4 || output.length > 260;
  const expandable = args.length > 3 || clipped || beat.output_truncated || beat.text_truncated;

  return (
    <div className="pbe-beat pbe-beat--tool">
      <Rail voice={beat.voice} />
      <div className="pbe-beat__body">
        <Meta
          beat={beat}
          more={
            expandable || open ? (
              <MoreButton
                opened={props.opened}
                onOpen={props.onOpen}
                collapsedLabel={
                  hidden > 0
                    ? `展开其余 ${hidden} 个参数${clipped ? "与完整结果" : ""}`
                    : "展开完整内容"
                }
              />
            ) : null
          }
        />
        <div className={`pbe-tool${failed ? " pbe-tool--failed" : ""}`}>
          <div className="pbe-tool__head">
            <span className="pbe-tool__title">{beat.tool || beat.name || "工具调用"}</span>
            {beat.name && beat.name !== beat.tool ? (
              <span className="pbe-tool__name pbe-mono">{beat.name}</span>
            ) : null}
            <StatusPill tone={tone} label={label} />
            {beat.result_chars ? <span className="pbe-tool__size">{num(beat.result_chars)} 字符</span> : null}
          </div>

          {shown.length ? (
            <div className="pbe-tool__args">
              {shown.map((arg) => (
                <div className="pbe-tool__arg" key={arg.key}>
                  <span className="pbe-tool__key">{arg.key}</span>
                  <span
                    className={`pbe-tool__value pbe-mono${open ? " pbe-tool__value--wrap" : ""}`}
                    title={open ? arg.value : undefined}
                  >
                    {open ? arg.value : arg.preview}
                  </span>
                </div>
              ))}
            </div>
          ) : null}

          {output ? (
            <div className={`pbe-tool__out${open ? " pbe-tool__out--open" : ""}`}>
              <span className="pbe-tool__out-label">结果</span>
              <pre className="pbe-tool__out-text">{output}</pre>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function PlanRow(props: { beat: Beat }): unknown {
  const beat = props.beat;
  const lines = (beat.text || "").split("\n").filter(Boolean);
  return (
    <div className="pbe-beat pbe-beat--plan">
      <Rail voice={beat.voice} />
      <div className="pbe-beat__body">
        <Meta beat={beat} extra={beat.steps ? <span>{beat.steps} 步</span> : null} />
        {lines.length ? (
          <ul className="pbe-plan">
            {lines.map((line, index) => {
              const matched = /^\[([a-z_]+)\]\s*(.*)$/.exec(line);
              const status = matched ? matched[1] : "pending";
              const text = matched ? matched[2] : line;
              return (
                <li className={`pbe-plan__item pbe-plan__item--${status}`} key={`${index}-${text}`}>
                  <span className="pbe-plan__mark" aria-hidden="true">
                    {status === "completed" ? "✓" : status === "in_progress" ? "▸" : "·"}
                  </span>
                  <span>{text}</span>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="pbe-beat__quiet">计划更新了 {beat.steps} 步，但这次没有带内容。</div>
        )}
      </div>
    </div>
  );
}

/** UI chatter, folded into one line: it is context, not conversation. */
function SystemRow(props: { beat: Beat }): unknown {
  const beat = props.beat;
  const [open, setOpen] = useState(false);
  const kinds = Array.from(new Set(beat.kinds));
  const summary = kinds.map((kind) => kind).join(" / ");
  return (
    <div className="pbe-beat pbe-beat--system">
      <Rail voice={beat.voice} />
      <div className="pbe-beat__body">
        <button type="button" className="pbe-system" aria-expanded={open} onClick={() => setOpen(!open)}>
          <span className="pbe-mono">{clock(beat.at)}</span>
          <span>
            {beat.events} 条{summary || "系统"}事件
          </span>
          <span className="pbe-system__act">{open ? "收起" : "看是哪几条"}</span>
        </button>
        {open ? (
          <ul className="pbe-system__list">
            {beat.kinds.map((kind, index) => (
              <li key={`${index}-${kind}`} className="pbe-mono">
                {kind}
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}
