/**
 * Everything the page is allowed to get from the host, in one place.
 *
 * The rule the rest of the source follows: no module reaches into
 * `window.QwenPaw` on its own.  Two consequences are worth naming, because both
 * are load-bearing:
 *
 * - The bearer token never reaches this side of the boundary.  Requests go to
 *   `/api/pawbench-eval/v1/...` (``getApiUrl`` supplies the ``/api``) and the
 *   plugin's backend adds the credential;
 *   `getApiToken` is used only where the proxy cannot carry the bytes (a
 *   download that must become a Blob, a raw package upload).
 * - The console's own bearer token is the *page's* credential, not the
 *   service's, which is why it is attached as `Authorization` here and never
 *   stored anywhere.
 */

export interface HostSdk {
  React: Record<string, unknown>;
  antd: Record<string, unknown>;
  antdIcons: Record<string, unknown>;
  getApiUrl: (path: string) => string;
  getApiToken: () => string;
}

/**
 * Mount point of this plugin's backend, relative to the console's own API root.
 *
 * Not spelled `/api/pawbench-eval`: ``getApiUrl`` prepends `/api`, so including
 * it here produces `/api/api/...`, which is a 404 on every call.
 */
export const API_BASE = "/pawbench-eval";

export function host(): HostSdk {
  const sdk = window.QwenPaw?.host;
  if (!sdk) {
    throw new Error("window.QwenPaw.host is not ready");
  }
  return sdk as unknown as HostSdk;
}

export function icons(): Record<string, unknown> {
  return host().antdIcons ?? {};
}

/** An error the service produced, carrying enough to explain it in the UI. */
export class HttpError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, message: string, code = "", details: unknown = null) {
    super(message);
    this.name = "HttpError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

function authHeaders(): Record<string, string> {
  const token = typeof host().getApiToken === "function" ? host().getApiToken() : "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function readResponse<T>(response: Response): Promise<T> {
  const text = await response.text();
  let data: any = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { message: text.slice(0, 400) };
    }
  }
  if (!response.ok) {
    throw new HttpError(
      response.status,
      (data && (data.message || data.error)) || `HTTP ${response.status}`,
      (data && data.error) || "",
      (data && data.details) ?? null,
    );
  }
  return data as T;
}

export async function call<T>(
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
): Promise<T> {
  const response = await fetch(host().getApiUrl(API_BASE + path), {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return readResponse<T>(response);
}

/** A package upload: the bytes are the body, the metadata is the query string. */
export async function uploadRaw<T>(path: string, file: Blob): Promise<T> {
  const response = await fetch(host().getApiUrl(API_BASE + path), {
    method: "POST",
    headers: { "Content-Type": "application/zip", ...authHeaders() },
    body: file,
  });
  return readResponse<T>(response);
}

/** Fetch a protected file through the proxy, then hand the bytes to the browser. */
export async function download(path: string, filename: string): Promise<void> {
  const response = await fetch(host().getApiUrl(API_BASE + path), { headers: authHeaders() });
  if (!response.ok) {
    throw new HttpError(response.status, `HTTP ${response.status}`);
  }
  saveBlob(await response.blob(), filename);
}

export function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename || "download";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.setTimeout(() => URL.revokeObjectURL(href), 2000);
}

/**
 * Put a value on the clipboard, or say it out loud when the browser will not.
 *
 * Both branches are used in practice: a console served over plain HTTP on a
 * LAN address has no `navigator.clipboard`, and silently doing nothing there
 * would look like the copy button was broken.
 */
export async function copyText(value: string, label: string): Promise<boolean> {
  if (!value) return false;
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
    /* fall through to the return value */
  }
  return false;
}

export function describeError(error: unknown): { code: string; message: string } {
  if (error instanceof HttpError) {
    return { code: error.code || `http_${error.status}`, message: error.message };
  }
  return { code: "unexpected_error", message: String((error as Error)?.message ?? error) };
}
