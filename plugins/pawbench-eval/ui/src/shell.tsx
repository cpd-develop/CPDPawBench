/**
 * The shell: a fixed rail and one visible module.
 *
 * Three things are done to this board at different times — submitting and
 * reading runs, curating datasets, pointing it at a service.  Stacking them on
 * one page meant scrolling past a form to read a score, so they became three
 * rows in a rail.  The rail also carries the connection state: "the service is
 * not answering" belongs somewhere always visible, not folded into a settings
 * panel you have to remember to open.
 *
 * The open report lives in the URL (`?job=`), so a report can be sent to
 * somebody as a link instead of as a screenshot.
 */

import { Alert, App, ConfigProvider, Tooltip } from "./host/antd";
import { api, ConnectionConfig, JobItem, ReportFormat } from "./api";
import { describeError, icons } from "./host/sdk";
import { useCallback, useEffect, useMemo, useState } from "./host/react";
import { DesignScope } from "./theme";
import { DatasetsModule } from "./modules/datasets";
import { JobsModule } from "./modules/jobs";
import { NewJobModal } from "./modules/new-job";
import { ReportModule } from "./modules/report";
import { SettingsModule } from "./modules/settings";
import { StatusPill } from "./ui/primitives";

type View = "jobs" | "datasets" | "settings";

const FORMAT_KEY = "pawbench-eval.format";

function readStored<T extends string>(key: string, allowed: readonly T[], fallback: T): T {
  try {
    const value = window.localStorage.getItem(key);
    return value && (allowed as readonly string[]).includes(value) ? (value as T) : fallback;
  } catch {
    return fallback;
  }
}

function store(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* a browser with storage disabled still gets a working page */
  }
}

export function Shell(): unknown {
  const [view, setView] = useState<View>("jobs");
  const [jobId, setJobId] = useState<string>(() => {
    const query = new URLSearchParams(window.location.search);
    return query.get("job") ?? "";
  });
  const [jobs, setJobs] = useState<JobItem[]>([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState<{ code: string; message: string } | null>(null);
  const [config, setConfig] = useState<ConnectionConfig | null>(null);
  const [bootError, setBootError] = useState<string>("");
  const [newOpen, setNewOpen] = useState(false);
  const [format, setFormat] = useState<ReportFormat>(() =>
    readStored(FORMAT_KEY, ["md", "html", "json", "zip"] as const, "md"),
  );

  const refreshJobs = useCallback(async () => {
    setJobsLoading(true);
    try {
      const list = await api.jobs();
      setJobs(list.jobs);
      setJobsError(null);
    } catch (err) {
      setJobsError(describeError(err));
    } finally {
      setJobsLoading(false);
    }
  }, []);

  useEffect(() => {
    api
      .config()
      .then(setConfig)
      .catch((err) => {
        const info = describeError(err);
        setBootError(`${info.code}：${info.message}`);
      });
    void refreshJobs();
  }, [refreshJobs]);

  // Poll only while something can change: a board that re-reads a list of
  // finished jobs every few seconds spends battery to tell nobody anything.
  const live = useMemo(
    () => jobs.some((job) => job.status === "running" || job.status === "queued" || job.status === "scheduled"),
    [jobs],
  );
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void refreshJobs(), 5000);
    return () => window.clearInterval(timer);
  }, [live, refreshJobs]);

  const openReport = useCallback((id: string) => {
    // A report belongs to 评测, so opening one puts the module there as well.
    // Without this the rail's answer ("which module am I in") and the render
    // branch's answer ("jobId or view") would be two different questions.
    setView("jobs");
    setJobId(id);
    const url = new URL(window.location.href);
    url.searchParams.set("job", id);
    window.history.replaceState({}, "", url.toString());
  }, []);

  const backToList = useCallback(() => {
    setJobId("");
    const url = new URL(window.location.href);
    url.searchParams.delete("job");
    window.history.replaceState({}, "", url.toString());
  }, []);

  // A report is a drill-down of 评测, not a fourth module: the rail keeps
  // 评测 current while one is open, so somebody two clicks deep still knows
  // which module they are in.  Computed rather than compared as
  // `view === key && !jobId` -- that spelling un-highlights every row, because
  // the report is reached with `view` still on "jobs".
  const surface: View = jobId ? "jobs" : view;

  const running = jobs.filter((job) => job.status === "running").length;

  const icon = icons() as Record<string, any>;
  const Flask = icon.ExperimentOutlined;
  const Database = icon.DatabaseOutlined;
  const Setting = icon.SettingOutlined;
  const Reload = icon.ReloadOutlined;

  const nav = [
    { key: "jobs" as View, label: "评测", count: running || null, glyph: Flask ? <Flask /> : null },
    { key: "datasets" as View, label: "数据集", count: null, glyph: Database ? <Database /> : null },
    { key: "settings" as View, label: "配置", count: null, glyph: Setting ? <Setting /> : null },
  ];

  return (
    <DesignScope ConfigProvider={ConfigProvider} className="pbe-root">
      <App>
        <div className="pbe-shell">
        <aside className="pbe-rail">
          <div className="pbe-rail__brand">
            <span aria-hidden="true">🧪</span>
            <span>PawBench 评测</span>
          </div>
          <nav className="pbe-rail__nav" aria-label="模块">
            {nav.map((item) => (
              <button
                key={item.key}
                type="button"
                className="pbe-nav-item"
                aria-current={surface === item.key ? "page" : undefined}
                onClick={() => {
                  setView(item.key);
                  backToList();
                }}
              >
                {item.glyph}
                <span>{item.label}</span>
                {item.count ? <span className="pbe-nav-item__count">{item.count}</span> : null}
              </button>
            ))}
          </nav>
          <Tooltip title="点一下重新探测服务">
            <button
              type="button"
              className="pbe-rail__foot"
              onClick={() => {
                setView("settings");
                backToList();
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: "var(--spacer-6)" }}>
                <StatusPill
                  tone={jobsError ? "err" : config?.has_token ? "ok" : "warn"}
                  label={jobsError ? "服务不可用" : config?.has_token ? "已连接" : "未配置 token"}
                />
                {jobsLoading ? (
                  <Reload style={{ fontSize: 12, color: "var(--text-tertiary)" }} />
                ) : null}
              </div>
              <div className="pbe-cell-sub" style={{ marginTop: "var(--spacer-4)" }}>
                {config?.base_url || "还没有填写地址"}
              </div>
            </button>
          </Tooltip>
        </aside>

        <main className="pbe-main">
          {bootError ? (
            <Alert
              type="warning"
              showIcon
              closable
              message="读不到连接配置"
              description={bootError}
              style={{ marginBottom: "var(--spacer-16)" }}
            />
          ) : null}

          {jobsError ? (
            <Alert
              type="error"
              showIcon
              closable
              message={jobsError.code}
              description={
                <>
                  {jobsError.message}
                  <br />
                  去看「配置」里的服务地址与 token；也可以点左边连接卡重新探测。
                </>
              }
              style={{ marginBottom: "var(--spacer-16)" }}
            />
          ) : null}

          {jobId ? (
            <ReportModule jobId={jobId} onBack={backToList} />
          ) : view === "jobs" ? (
            <JobsModule
              jobs={jobs}
              loading={jobsLoading}
              subject={config?.subject ?? ""}
              onOpen={openReport}
              onRefresh={() => void refreshJobs()}
              onNew={() => setNewOpen(true)}
            />
          ) : view === "datasets" ? (
            <DatasetsModule subject={config?.subject ?? ""} />
          ) : (
            <SettingsModule
              config={config}
              format={format}
              onSaved={(next) => {
                setConfig(next);
                void refreshJobs();
              }}
              onFormat={(value) => {
                setFormat(value);
                store(FORMAT_KEY, value);
              }}
            />
          )}
        </main>

        </div>

        <NewJobModal
          open={newOpen}
          onClose={() => setNewOpen(false)}
          onIdentity={(subject) => setConfig((prev) => (prev ? { ...prev, subject } : prev))}
          onSubmitted={(job) => {
            setNewOpen(false);
            void refreshJobs();
            openReport(job.job_id);
          }}
        />
      </App>
    </DesignScope>
  );
}
