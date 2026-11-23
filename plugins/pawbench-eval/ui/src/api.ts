/**
 * The service, as this page sees it.
 *
 * One function per route, and one type per payload.  The types are written from
 * what the handlers return (``service/reports.py``, ``service/jobs.py``,
 * ``service/datasets.py``) and mark the fields the service omits rather than
 * emits empty: ``score`` is ``null`` for a task nobody could score, and
 * ``trace_id``/``session_id`` are missing entirely on rows written before those
 * columns existed.  Treating either as zero-length would flatter a run that
 * measured nothing.
 */

import { call, uploadRaw } from "./host/sdk";

export type Sensitivity = "shared" | "full";
export type ReportFormat = "md" | "html" | "json" | "zip";

export interface Window {
  kind: "immediate" | "night" | "range";
  start?: string | null;
  end?: string | null;
  timezone?: string;
}

export interface JobItem {
  job_id: string;
  submitter: string;
  status: string;
  queue_pos: number | null;
  purpose: string;
  product: string;
  acp_url: string;
  window_kind: string;
  not_before: string | null;
  not_after: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  env_fingerprint: unknown;
  task_count: number;
  tasks_finished: number;
  tasks_failed: number;
  score: number | null;
}

export interface JobList {
  jobs: JobItem[];
  count: number;
}

export interface TaskArtifact {
  path: string;
  size: number;
  sha256: string;
  kind: string;
}

/**
 * One file the task handed the agent, as declared by the task package.
 *
 * ``copy`` is which of the two copies answered: the dataset's own file
 * (``dataset``) or the one this attempt laid into its session directory
 * (``attempt``).  They are the same bytes unless something changed on disk
 * since the run, and a reader is entitled to know which one they are looking at.
 */
export interface TaskAttachment {
  path: string;
  size: number | null;
  copy: "dataset" | "attempt" | null;
}

/**
 * What one preview shows.
 *
 * ``kind`` describes the *file*: ``text`` and ``image`` are inline, ``binary``
 * is a name and a download link.  ``bytes`` is the file and ``shown_bytes`` is
 * what came back -- they differ exactly when the service trimmed or declined to
 * inline, which is what ``truncated`` reports.
 */
export interface FilePreview {
  path: string;
  kind: "text" | "image" | "binary";
  media_type: string;
  bytes: number;
  shown_bytes: number;
  truncated: boolean;
  text?: string;
  data_url?: string;
}

export interface TaskEntry {
  task_id: string;
  attempt: number;
  status: string;
  score: number | null;
  grading_type: string | null;
  failure_reason: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_s: number | null;
  protocol_written: number;
  out_of_band_count: number;
  subject_model_reported: string[] | null;
  resolved_from: string[];
  automated_breakdown: Record<string, number> | null;
  trace_id: string | null;
  session_id: string | null;
  artifacts: TaskArtifact[];
  name?: string;
  labels?: { scenario?: string; capabilities?: string[] } & Record<string, unknown>;
  has_attachments?: boolean;
  attachments?: TaskAttachment[];
  prompt?: string | null;
  // Full tier only.
  /**
   * What the judge wrote.  A string when a model judged the task, an object
   * when a rule did, and `{}` when it had nothing to add -- so it is typed as
   * unknown and formatted on the way to the page.  Rendering the object
   * straight into a `<pre>` is a React crash, not a formatting problem.
   */
  judge_notes?: unknown;
  judge_served_models?: string[] | null;
  workspace_path?: string | null;
  transcript_path?: string | null;
  expected_behavior?: string | null;
  rubric_excerpt?: string | null;
  downloads?: string[];
}

export interface JobSource {
  dataset_id: string;
  name?: string;
  task_count: number;
  [key: string]: unknown;
}

/** The job's mean score, with the range it came from. */
export interface ScoreSummary {
  mean: number | null;
  count: number;
  best: number | null;
  worst: number | null;
}

/** ``progress.by_status`` is keyed by task status, which is an open set. */
export interface JobProgress {
  total?: number;
  scored?: number;
  by_status?: Record<string, number>;
}

export interface JobDetail {
  job_id: string;
  sensitivity: Sensitivity;
  generated_at: string;
  status: string;
  error: string | null;
  submitter: string;
  product: string;
  purpose: string;
  acp_url: string;
  window: Window;
  env_fingerprint: unknown;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  sources: JobSource[];
  progress: JobProgress;
  /** A summary object on the detail route; a bare number on the queue route. */
  score: ScoreSummary | number | null;
  slices?: Record<string, Record<string, number>>;
  tasks: TaskEntry[];
  full_only: boolean;
}

export interface TranscriptEvent {
  kind: string;
  at: string;
  chars?: number;
  tool?: string;
  status?: string;
  args?: Record<string, unknown>;
  result_chars?: number;
  text?: string;
}

export interface TranscriptPage {
  task_id: string;
  attempt: number;
  cursor: number;
  limit: number;
  total_events: number;
  next_cursor: number | null;
  events: TranscriptEvent[];
  transcript_state: string;
  damaged_events: number;
}

export interface TaskDetail extends TaskEntry {
  transcript: TranscriptPage;
}

export interface DatasetItem {
  id: string;
  name: string;
  owner: string;
  kind: string;
  description: string;
  categories: string[];
  task_count: number;
  updated_at: string;
}

export interface DatasetList {
  datasets: DatasetItem[];
}

export interface CategoryList {
  categories: { name: string; [key: string]: unknown }[];
}

export interface ResolveResult {
  task_count: number;
  by_dataset?: Record<string, number>;
  by_category?: Record<string, number>;
  duplicates_removed?: number;
  unknown_ids?: string[];
  [key: string]: unknown;
}

export interface ConnectionConfig {
  base_url: string;
  has_token: boolean;
  token_hint: string;
  subject: string;
  source: string;
}

export interface ProbeResult {
  reachable: boolean;
  authorized: boolean;
  detail: string;
  [key: string]: unknown;
}

export interface ReportLink {
  job_id: string;
  format: string;
  sensitivity: string;
  filename: string;
  sha256: string;
  size: number;
  url: string;
  expires_at: string;
  stale_before: string | null;
}

export interface SubmitBody {
  acp_url: string;
  product: string;
  purpose: string;
  selector: { categories: string[]; datasets: string[] };
  window: Window;
  sensitivity?: Sensitivity;
}

const q = encodeURIComponent;

export const api = {
  config: () => call<ConnectionConfig>("GET", "/config"),
  saveConfig: (body: { base_url?: string; token?: string; subject?: string }) =>
    call<ConnectionConfig>("PUT", "/config", body),
  probe: () => call<ProbeResult>("POST", "/config/probe", {}),
  learnIdentity: (jobId: string) =>
    call<{ subject: string }>("POST", `/identity/${q(jobId)}`, {}),

  jobs: () => call<JobList>("GET", "/v1/jobs"),
  job: (jobId: string) => call<JobItem>("GET", `/v1/jobs/${q(jobId)}`),
  submit: (body: SubmitBody) => call<JobItem>("POST", "/v1/jobs", body),
  reorder: (jobId: string, target: Record<string, unknown>) =>
    call<JobItem>("PATCH", `/v1/jobs/${q(jobId)}`, target),
  cancel: (jobId: string, reason: string) =>
    call<JobItem>("POST", `/v1/jobs/${q(jobId)}/cancel`, { reason }),

  detail: (jobId: string, sensitivity: Sensitivity) =>
    call<JobDetail>("GET", `/v1/jobs/${q(jobId)}/detail?sensitivity=${sensitivity}`),
  taskDetail: (jobId: string, taskId: string, sensitivity: Sensitivity, attempt: number) =>
    call<TaskDetail>(
      "GET",
      `/v1/jobs/${q(jobId)}/tasks/${q(taskId)}/detail?sensitivity=${sensitivity}&attempt=${attempt}`,
    ),
  results: (jobId: string) =>
    call<Record<string, unknown>>("GET", `/v1/jobs/${q(jobId)}/results`),
  transcript: (jobId: string, taskId: string, attempt: number, cursor: number) =>
    call<TranscriptPage>(
      "GET",
      `/v1/jobs/${q(jobId)}/transcript?task_id=${q(taskId)}&attempt=${attempt}&cursor=${cursor}`,
    ),

  /**
   * One file's contents, trimmed.
   *
   * Two paths rather than one with a `kind` query: an artifact and an
   * attachment are two different files, and the caller always knows which one
   * it is holding.
   */
  preview: (
    jobId: string,
    taskId: string,
    attempt: number,
    kind: "artifacts" | "attachments",
    path: string,
  ) =>
    call<FilePreview>(
      "GET",
      `/v1/jobs/${q(jobId)}/tasks/${q(taskId)}/attempts/${attempt}/${kind}/preview?path=${q(path)}`,
    ),

  /** Where a download goes, so the proxy can add the token on the way out. */
  fileUrl: (
    jobId: string,
    taskId: string,
    attempt: number,
    kind: "artifacts" | "attachments",
    path: string,
  ) => `/v1/jobs/${jobId}/tasks/${taskId}/attempts/${attempt}/${kind}?path=${q(path)}`,
  report: (jobId: string, format: ReportFormat, sensitivity: Sensitivity) =>
    call<ReportLink>(
      "GET",
      `/v1/jobs/${q(jobId)}/report?format=${format}&sensitivity=${sensitivity}`,
    ),

  datasets: () => call<DatasetList>("GET", "/v1/datasets"),
  categories: () => call<CategoryList>("GET", "/v1/dataset-categories"),
  resolve: (selector: { categories: string[]; datasets: string[] }) =>
    call<ResolveResult>("POST", "/v1/datasets/resolve", { selector }),
  createDataset: (body: Record<string, unknown>) =>
    call<DatasetItem>("POST", "/v1/datasets", body),
  editDataset: (datasetId: string, body: Record<string, unknown>) =>
    call<DatasetItem>("PUT", `/v1/datasets/${q(datasetId)}`, body),
  deleteDataset: (datasetId: string) => call<unknown>("DELETE", `/v1/datasets/${q(datasetId)}`),
  uploadPackage: (file: Blob, query: string) =>
    uploadRaw<DatasetItem>(`/v1/datasets/packages?${query}`, file),
  createCategory: (body: Record<string, unknown>) =>
    call<unknown>("POST", "/v1/dataset-categories", body),
  deleteCategory: (name: string) =>
    call<unknown>("DELETE", `/v1/dataset-categories/${q(name)}`),
};
