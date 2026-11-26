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
}

/**
 * One line of the transcript, as the timeline draws it.
 *
 * The default page answers sizes: ``chars`` and ``result_chars`` say how much
 * went past, ``tool`` says which tool ran, and the subject's own words stay on
 * the server.  ``detail`` (the dashboard asks for it, the judge and the MCP
 * tools never do) adds the fields below the line: ``text`` is the opening of
 * what was said, ``output`` the opening of what came back, ``tool_call_id`` the
 * handle that pairs a call with the updates that finish it.  Every added field
 * is absent rather than empty when there is nothing to say.
 */
export interface TranscriptEvent {
  kind: string;
  at: string;
  chars?: number;
  tool?: string;
  status?: string;
  args?: Record<string, unknown>;
  result_chars?: number;
  name?: string;
  tool_call_id?: string;
  text?: string;
  text_truncated?: boolean;
  output?: string;
  output_truncated?: boolean;
  steps?: number;
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

/**
 * One fold of the transcript: the thing a person would name as one beat.
 *
 * ``from``/``to`` are the service's private line handles.  They travel with
 * the beat so opening it can fetch its full content, but are never drawn as a
 * cursor: the reader pages by ``index`` in the filtered list, not by raw line.
 */
export interface Beat {
  key: string;
  index: number;
  voice: "user" | "assistant" | "thought" | "tool" | "plan" | "system";
  label: string;
  at: string;
  from: number;
  to: number;
  events: number;
  text: string;
  text_truncated: boolean;
  chars: number;
  tool: string;
  name: string;
  status: string;
  args: Record<string, string>;
  result_chars: number;
  output: string;
  output_truncated: boolean;
  steps: number;
  kinds: string[];
}

export type BeatFilter = "all" | "talk" | "tool" | "thought" | "plan";

export const BeatFilters: { value: BeatFilter; label: string }[] = [
  { value: "all", label: "全部" },
  { value: "talk", label: "对话" },
  { value: "tool", label: "工具" },
  { value: "thought", label: "思考" },
  { value: "plan", label: "计划" },
];

export interface BeatsPage {
  task_id: string;
  attempt: number;
  page: number;
  size: number;
  voice: BeatFilter;
  total_beats: number;
  next_page: number | null;
  beats: Beat[];
  counts: Record<BeatFilter, number>;
  transcript_state: string;
  damaged_events: number;
  total_events: number;
}

/** The whole words of one beat, fetched only when a reader opens it. */
export interface BeatContent {
  task_id: string;
  attempt: number;
  index: number;
  voice: BeatFilter;
  kind?: string;
  text: string;
  args: Record<string, string>;
  output: string;
  text_truncated: boolean;
  output_truncated: boolean;
  transcript_state: string;
  found: boolean;
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

/**
 * One task inside a dataset, as the catalogue lists it.
 *
 * Not the task itself: name, labels, grading *kind* and how many files come
 * with it.  The question lives one request further in (``DatasetTaskDetail``),
 * because a listing that quoted every prompt would be a corpus leak with a
 * scrollbar.
 */
export interface DatasetTaskEntry {
  task_id: string;
  name: string;
  grading_type: string;
  timeout_seconds: number;
  has_attachments: boolean;
  attachment_count: number;
  labels: Record<string, unknown>;
}

export interface DatasetDetail {
  id: string;
  name: string;
  owner: string;
  kind: string;
  description: string;
  categories: string[];
  filter_spec: Record<string, unknown>;
  task_count: number;
  tasks: DatasetTaskEntry[];
}

/** One fixture a task declares, and whether the file is still on disk. */
export interface DatasetAttachment {
  path: string;
  size: number | null;
  present: boolean;
}

/**
 * One task of one dataset: the question, and what came with it.
 *
 * ``unreadable`` is the service's answer for a markdown file that no longer
 * parses: the labels are still there (they come from the index), and the
 * prompt is ``null``.  That is a state to show, not an error to hide -- the
 * person looking at the dataset is the one who can fix the file.
 */
export interface DatasetTaskDetail {
  dataset_id: string;
  task_id: string;
  name: string;
  grading_type: string;
  timeout_seconds: number;
  labels: Record<string, unknown>;
  prompt: string | null;
  expected_behavior: string | null;
  /**
   * How the task is scored: the criteria list and the judge rubric.
   *
   * The rubric is text about what a good answer looks like; ``automated_checks``
   * -- the script that carries the expected values -- is deliberately absent
   * from this payload, and ``has_automated_checks`` is the only thing that says
   * it exists.
   */
  grading_criteria: string[];
  llm_judge_rubric: string | null;
  grading_weights: Record<string, number>;
  has_automated_checks: boolean;
  attachments: DatasetAttachment[];
  unreadable: string | null;
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
  /**
   * What the run's numbers should be read against -- model, build, machine.
   *
   * The submitter's own vocabulary, stored verbatim: the service renames
   * nothing and requires nothing, and an omitted field stays omitted (the
   * report then says the submission carried no fingerprint) rather than
   * becoming an invented one.
   */
  env_fingerprint?: Record<string, string>;
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

  detail: (jobId: string) => call<JobDetail>("GET", `/v1/jobs/${q(jobId)}/detail`),
  taskDetail: (jobId: string, taskId: string, attempt: number) =>
    call<TaskDetail>(
      "GET",
      `/v1/jobs/${q(jobId)}/tasks/${q(taskId)}/detail?attempt=${attempt}`,
    ),
  results: (jobId: string) =>
    call<Record<string, unknown>>("GET", `/v1/jobs/${q(jobId)}/results`),
  /**
   * One page of a task's timeline.
   *
   * ``detail`` asks for the readable version -- bounded previews of speech and
   * tool results -- because the dashboard is where a person argues with a score
   * and "340 chars" cannot be argued with.  The judge-facing callers leave it
   * off and keep the size-only page.
   */
  transcript: (jobId: string, taskId: string, attempt: number, cursor: number, detail = false) =>
    call<TranscriptPage>(
      "GET",
      `/v1/jobs/${q(jobId)}/transcript?task_id=${q(taskId)}&attempt=${attempt}&cursor=${cursor}` +
        (detail ? "&detail=1" : ""),
    ),

  /**
   * One page of the run's beats, folded on the service.
   *
   * The reader pages by beat -- ten sentences, not ten notifications -- and
   * filters on the same folded list, so a page of "工具" holds ten tool calls
   * rather than ten lines of which none may be a tool.  Raw line cursors stay
   * behind the service; a beat is named by its index in the filtered list.
   */
  beats: (
    jobId: string,
    taskId: string,
    attempt: number,
    page: number,
    size: number,
    voice: BeatFilter,
  ) =>
    call<BeatsPage>(
      "GET",
      `/v1/jobs/${q(jobId)}/beats?task_id=${q(taskId)}&attempt=${attempt}` +
        `&page=${page}&size=${size}&voice=${q(voice)}`,
    ),
  /** Complete text, arguments and result of one opened beat. */
  beatContent: (
    jobId: string,
    taskId: string,
    attempt: number,
    index: number,
    voice: BeatFilter,
  ) =>
    call<BeatContent>(
      "GET",
      `/v1/jobs/${q(jobId)}/beats/content?task_id=${q(taskId)}&attempt=${attempt}` +
        `&index=${index}&voice=${q(voice)}`,
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
  report: (jobId: string, format: ReportFormat) =>
    call<ReportLink>("GET", `/v1/jobs/${q(jobId)}/report?format=${format}`),

  datasets: () => call<DatasetList>("GET", "/v1/datasets"),
  datasetDetail: (datasetId: string) => call<DatasetDetail>("GET", `/v1/datasets/${q(datasetId)}`),
  datasetTask: (datasetId: string, taskId: string) =>
    call<DatasetTaskDetail>("GET", `/v1/datasets/${q(datasetId)}/tasks/${q(taskId)}`),
  /**
   * A fixture's contents, before any run exists.
   *
   * The same shape an artifact preview answers with, from the same function in
   * the service: the file a task comes with and the file an agent wrote back
   * are read with one set of rules.
   */
  datasetFixture: (datasetId: string, taskId: string, path: string) =>
    call<FilePreview>(
      "GET",
      `/v1/datasets/${q(datasetId)}/tasks/${q(taskId)}/attachments/preview?path=${q(path)}`,
    ),
  /**
   * The task's own markdown.
   *
   * The fallback the detail page offers beside the parsed fields: if a rubric
   * resists parsing, the file itself is one click away.  Previewed through the
   * same reader as a fixture, so the trim is the same.
   */
  datasetTaskSource: (datasetId: string, taskId: string) =>
    call<FilePreview>("GET", `/v1/datasets/${q(datasetId)}/tasks/${q(taskId)}/source`),
  /** Where a fixture download goes, so the proxy can add the token on the way out. */
  datasetFixtureUrl: (datasetId: string, taskId: string, path: string) =>
    `/v1/datasets/${q(datasetId)}/tasks/${q(taskId)}/attachments?path=${q(path)}`,
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
