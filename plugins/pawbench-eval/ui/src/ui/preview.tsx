/**
 * One file, as the dialog that opened it can show it.
 *
 * Two sections of the task view point here -- the attachments the task handed
 * the agent, and the files the agent wrote back -- because the question a reader
 * has about either is the same one: *what is in it*.  The service decides what
 * `kind` of file it is and trims it; this only renders the answer.
 *
 * The trim is not an error state.  A 64 MB log arrives as text cut at the cap,
 * with the note saying so, because the first screen of a log is usually the
 * part that explains the failure and refusing to show any of it would send the
 * reader to a download to find that out.
 */

import { Alert, Button, Modal, Skeleton } from "../host/antd";
import { describeError, download } from "../host/sdk";
import { useEffect, useState } from "../host/react";
import { api, FilePreview } from "../api";
import { EmptyHint, bytes } from "./primitives";

export interface PreviewTarget {
  kind: "artifacts" | "attachments" | "fixture" | "source";
  path: string;
  canDownload: boolean;
}

/**
 * Where the bytes come from: one attempt of one run, or one task of one dataset.
 *
 * Both are "a declared file", and both are answered by the service's single
 * preview function, so the dialog does not need a second body for the second
 * case -- only a second way to ask for the bytes.
 */
export type PreviewSource =
  | { kind: "job"; jobId: string; taskId: string; attempt: number }
  | { kind: "dataset"; datasetId: string; taskId: string };

export function PreviewModal(props: {
  source: PreviewSource;
  target: PreviewTarget;
  onClose: () => void;
}): unknown {
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [error, setError] = useState("");
  const { kind, path } = props.target;
  const { source } = props;
  // The source object is rebuilt on every render, so the effect keys off its
  // fields instead: an identity dependency would refetch on each keystroke
  // anywhere on the page.
  const sourceKey = JSON.stringify(source);

  useEffect(() => {
    let alive = true;
    setPreview(null);
    setError("");
    const asked =
      source.kind === "job"
        ? api.preview(source.jobId, source.taskId, source.attempt, kind as "artifacts" | "attachments", path)
        : kind === "source"
          ? api.datasetTaskSource(source.datasetId, source.taskId)
          : api.datasetFixture(source.datasetId, source.taskId, path);
    asked
      .then((answer) => {
        if (alive) setPreview(answer);
      })
      .catch((err) => {
        if (alive) setError(describeError(err).message);
      });
    return () => {
      alive = false;
    };
  }, [sourceKey, kind, path]);

  const name = path.split("/").pop() || path;

  function save(): void {
    // A fixture of a dataset has no attempt, so its download is its own route;
    // the job's artifacts and attachments share the one the report already uses.
    const url =
      source.kind === "dataset"
        ? api.datasetFixtureUrl(source.datasetId, source.taskId, path)
        : kind === "artifacts" || kind === "attachments"
          ? api.fileUrl(source.jobId, source.taskId, source.attempt, kind, path)
          : "";
    if (url) {
      // The download button is the last action in the dialog; a rejected
      // promise here used to leave it doing nothing at all.  The same Alert
      // that reports a failed preview can report a failed save.
      void download(url, name).catch((err: unknown) => setError(describeError(err).message));
    }
  }

  return (
    <Modal
      open
      width={920}
      onCancel={props.onClose}
      title={
        <div className="pbe-preview__title">
          <span className="pbe-mono">{path}</span>
          {preview ? <span className="pbe-cell-sub">{bytes(preview.bytes)}</span> : null}
        </div>
      }
      footer={
        <>
          {props.target.canDownload ? (
            <Button onClick={save} disabled={!preview}>
              下载
            </Button>
          ) : null}
          <Button type="primary" onClick={props.onClose}>
            关闭
          </Button>
        </>
      }
    >
      {error ? <Alert type="error" showIcon message="读不到这个文件" description={error} /> : null}
      {!error && !preview ? <Skeleton active paragraph={{ rows: 6 }} /> : null}
      {preview ? <PreviewBody preview={preview} /> : null}
    </Modal>
  );
}

function PreviewBody(props: { preview: FilePreview }): unknown {
  const { preview } = props;

  if (preview.kind === "binary") {
    return (
      <EmptyHint>
        {`${preview.media_type}，${bytes(preview.bytes)}，不能在页面里打开。下载后用本地程序查看。`}
      </EmptyHint>
    );
  }

  if (preview.kind === "image") {
    if (!preview.data_url) {
      return (
        <EmptyHint>{`图片 ${bytes(preview.bytes)}，超过内联预览的上限了，下载后查看。`}</EmptyHint>
      );
    }
    return <img className="pbe-preview__image" src={preview.data_url} alt={preview.path} />;
  }

  return (
    <>
      {preview.truncated ? (
        <div className="pbe-preview__note">
          {`只显示前 ${bytes(preview.shown_bytes)}，全文 ${bytes(preview.bytes)}——下载可以拿到完整的。`}
        </div>
      ) : null}
      <pre className="pbe-block pbe-preview">{preview.text || "（空文件）"}</pre>
    </>
  );
}
