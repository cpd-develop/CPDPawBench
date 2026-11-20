/**
 * PawBench Eval — dashboard (runtime-loaded plugin frontend).
 *
 * The host fetches this file, wraps it in a Blob and `import()`s it, so it is a
 * module with no relative imports and no bundler: React, antd and the icon set
 * come from `window.QwenPaw.host`.
 *
 * Layout: three modules behind a fixed rail rather than one long page.
 * Submitting a run, curating datasets and pointing the board at a service are
 * three different jobs done by the same person at different times, and stacking
 * them meant scrolling past a form to read a score. The rail keeps one of them
 * on screen; the other two cost a click.
 *
 * Colour never appears literally: every surface/text/border value comes from
 * `theme.useToken()`, which is the host's own theme, so light and dark are the
 * same code path and the design system's "no hardcoded colour" rule holds
 * without a second stylesheet.
 */
(function () {
  "use strict";

  var Q = window.QwenPaw;
  if (!Q || !Q.host || !Q.registerRoutes) {
    console.error("[pawbench-eval] window.QwenPaw host SDK is not ready");
    return;
  }

  var host = Q.host;
  var React = host.React;
  var antd = host.antd;
  var icons = host.antdIcons || {};
  var h = React.createElement;
  var useState = React.useState;
  var useEffect = React.useEffect;
  var useMemo = React.useMemo;
  var useCallback = React.useCallback;

  var Button = antd.Button;
  var Table = antd.Table;
  var Tag = antd.Tag;
  var Space = antd.Space;
  var Select = antd.Select;
  var Input = antd.Input;
  var Modal = antd.Modal;
  var Tabs = antd.Tabs;
  var Segmented = antd.Segmented;
  var Alert = antd.Alert;
  var Tooltip = antd.Tooltip;
  var Empty = antd.Empty;
  var Spin = antd.Spin;
  var Popconfirm = antd.Popconfirm;
  var DatePicker = antd.DatePicker;
  var Upload = antd.Upload;
  var Typography = antd.Typography;
  var Progress = antd.Progress;
  var message = antd.message;
  var useToken = antd.theme.useToken;

  var Text = Typography.Text;
  var Paragraph = Typography.Paragraph;

  // ── constants ───────────────────────────────────────────────────────────

  var API = "/pawbench-eval";
  var POLL_MS = 5000;
  var LS = "pawbench-eval.";
  var ORDERABLE = { queued: 1, scheduled: 1 };
  var TERMINAL = { finished: 1, failed: 1, canceled: 1 };
  var REPORT_FORMATS = ["json", "md", "html", "zip"];
  var FILTER_KEYS = [
    "scenario",
    "capability",
    "complexity",
    "environment",
    "modality",
    "source",
    "grading_type",
  ];

  //: Task statuses that are not job statuses: the runner records these per task
  //: and they have no Chinese spelling, so they are shown as the token an
  //: operator would grep for.
  var TASK_STATUS_TEXT = { skipped: "跳过", no_artifacts: "无产物", missing: "缺失" };

  // ── helpers ─────────────────────────────────────────────────────────────

  function pad(value) {
    return value < 10 ? "0" + value : String(value);
  }

  function localZone() {
    try {
      return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
    } catch (err) {
      return "";
    }
  }

  function offsetLabel(date) {
    var minutes = -date.getTimezoneOffset();
    var sign = minutes >= 0 ? "+" : "-";
    var abs = Math.abs(minutes);
    return "UTC" + sign + pad(Math.floor(abs / 60)) + ":" + pad(abs % 60);
  }

  function asDate(iso) {
    if (!iso) return null;
    var date = new Date(iso);
    return isNaN(date.getTime()) ? null : date;
  }

  /** `MM-DD HH:mm` in the reader's own zone — the one they schedule in. */
  function fmtShort(iso) {
    var date = asDate(iso);
    if (!date) return "—";
    return (
      pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + " " +
      pad(date.getHours()) + ":" + pad(date.getMinutes())
    );
  }

  function fmtFull(iso) {
    var date = asDate(iso);
    if (!date) return "—";
    return (
      date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate()) + " " +
      pad(date.getHours()) + ":" + pad(date.getMinutes()) + ":" + pad(date.getSeconds())
    );
  }

  function fmtUtc(iso) {
    var date = asDate(iso);
    if (!date) return "—";
    return (
      date.getUTCFullYear() + "-" + pad(date.getUTCMonth() + 1) + "-" + pad(date.getUTCDate()) + " " +
      pad(date.getUTCHours()) + ":" + pad(date.getUTCMinutes())
    );
  }

  /** "还有 2 小时 13 分起跑" — an empty cell reads as broken, this reads as waiting. */
  function untilText(iso) {
    var date = asDate(iso);
    if (!date) return "";
    var diff = date.getTime() - Date.now();
    if (diff <= 0) return "已到时间，等待调度";
    var minutes = Math.floor(diff / 60000);
    var days = Math.floor(minutes / 1440);
    var hours = Math.floor((minutes % 1440) / 60);
    var rest = minutes % 60;
    if (days > 0) return "还有 " + days + " 天 " + hours + " 小时";
    if (hours > 0) return "还有 " + hours + " 小时 " + rest + " 分";
    if (minutes > 0) return "还有 " + rest + " 分";
    return "不到 1 分钟";
  }

  /** How long the run itself took, in the units a reader thinks in. */
  function fmtDuration(seconds) {
    var value = Number(seconds);
    if (!isFinite(value) || value <= 0) return "—";
    if (value < 60) return value.toFixed(1) + "s";
    var minutes = Math.floor(value / 60);
    var rest = Math.round(value % 60);
    if (minutes < 60) return minutes + "m " + rest + "s";
    return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m";
  }

  function fmtPct(value) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    return (Number(value) * 100).toFixed(1) + "%";
  }

  function fmtNum(value, digits) {
    if (value === null || value === undefined || isNaN(value)) return "—";
    return Number(value).toFixed(digits === undefined ? 3 : digits);
  }

  function shortId(id) {
    if (!id) return "";
    return id.replace(/^job-/, "").slice(0, 8);
  }

  function statusMeta(status) {
    switch (status) {
      case "running":
        return { text: "运行中", color: "processing" };
      case "queued":
        return { text: "已排队", color: "blue" };
      case "scheduled":
        return { text: "待起跑", color: "gold" };
      case "finished":
        return { text: "已完成", color: "success" };
      case "failed":
        return { text: "失败", color: "error" };
      case "canceled":
        return { text: "已取消", color: "default" };
      case "new":
        return { text: "已登记", color: "default" };
      default:
        return { text: status || "未知", color: "default" };
    }
  }

  function windowLabel(kind) {
    if (kind === "immediate") return "即时";
    if (kind === "night") return "夜间固定窗";
    if (kind === "custom") return "自定义区间";
    return kind || "—";
  }

  function errOf(err) {
    return {
      code: (err && err.code) || "request_failed",
      message: (err && err.message) || "请求失败",
      details: (err && err.details) || null,
    };
  }

  function iconOf(name, fallback) {
    var Component = icons[name];
    return Component ? h(Component) : fallback;
  }

  function readLS(key, fallback) {
    try {
      var value = window.localStorage.getItem(LS + key);
      return value === null ? fallback : value;
    } catch (err) {
      return fallback;
    }
  }

  function writeLS(key, value) {
    try {
      window.localStorage.setItem(LS + key, value);
    } catch (err) {
      /* private mode: the form still works, it just forgets */
    }
  }

  function copyText(value, label) {
    if (!value) return;
    try {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(String(value));
        message.success((label || "已复制") + "：" + String(value).slice(0, 40));
        return;
      }
    } catch (err) {
      /* fall through to the hint below */
    }
    message.info(String(value));
  }

  // ── api ─────────────────────────────────────────────────────────────────

  function call(method, path, body) {
    var url = host.getApiUrl(API + path);
    var headers = { "Content-Type": "application/json" };
    var token = typeof host.getApiToken === "function" ? host.getApiToken() : "";
    if (token) headers.Authorization = "Bearer " + token;
    return fetch(url, {
      method: method,
      headers: headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(readResponse);
  }

  function readResponse(response) {
    return response.text().then(function (text) {
      var data = null;
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (err) {
          data = { message: text.slice(0, 400) };
        }
      }
      if (!response.ok) {
        var error = new Error((data && (data.message || data.error)) || "HTTP " + response.status);
        error.status = response.status;
        error.code = data && data.error;
        error.details = data && data.details;
        throw error;
      }
      return data;
    });
  }

  /** A raw-body upload: the package bytes are the body, metadata is the query. */
  function uploadPackage(file, query) {
    var url = host.getApiUrl(API + "/v1/datasets/packages?" + query);
    var headers = {};
    var token = typeof host.getApiToken === "function" ? host.getApiToken() : "";
    if (token) headers.Authorization = "Bearer " + token;
    headers["Content-Type"] = "application/zip";
    return fetch(url, { method: "POST", headers: headers, body: file }).then(readResponse);
  }

  /** Fetch a protected file through the proxy, then hand it to the browser. */
  function downloadPath(path, filename) {
    var url = host.getApiUrl(API + path);
    var headers = {};
    var token = typeof host.getApiToken === "function" ? host.getApiToken() : "";
    if (token) headers.Authorization = "Bearer " + token;
    return fetch(url, { headers: headers })
      .then(function (response) {
        if (!response.ok) throw new Error("HTTP " + response.status);
        return response.blob();
      })
      .then(function (blob) {
        saveBlob(blob, filename);
      });
  }

  function saveBlob(blob, filename) {
    var href = URL.createObjectURL(blob);
    var anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = filename || "download";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    setTimeout(function () {
      URL.revokeObjectURL(href);
    }, 2000);
  }

  var api = {
    config: function () {
      return call("GET", "/config");
    },
    saveConfig: function (body) {
      return call("PUT", "/config", body);
    },
    probe: function () {
      return call("POST", "/config/probe", {});
    },
    learnIdentity: function (jobId) {
      return call("POST", "/identity/" + encodeURIComponent(jobId), {});
    },
    datasets: function () {
      return call("GET", "/v1/datasets");
    },
    categories: function () {
      return call("GET", "/v1/dataset-categories");
    },
    resolve: function (selector) {
      return call("POST", "/v1/datasets/resolve", { selector: selector });
    },
    jobs: function () {
      return call("GET", "/v1/jobs");
    },
    job: function (jobId) {
      return call("GET", "/v1/jobs/" + encodeURIComponent(jobId));
    },
    submit: function (body) {
      return call("POST", "/v1/jobs", body);
    },
    reorder: function (jobId, target) {
      return call("PATCH", "/v1/jobs/" + encodeURIComponent(jobId), target);
    },
    cancel: function (jobId, reason) {
      return call("POST", "/v1/jobs/" + encodeURIComponent(jobId) + "/cancel", {
        reason: reason || "",
      });
    },
    detail: function (jobId, sensitivity) {
      return call(
        "GET",
        "/v1/jobs/" + encodeURIComponent(jobId) + "/detail?sensitivity=" + sensitivity,
      );
    },
    taskDetail: function (jobId, taskId, sensitivity, attempt) {
      return call(
        "GET",
        "/v1/jobs/" + encodeURIComponent(jobId) + "/tasks/" + encodeURIComponent(taskId) +
          "/detail?sensitivity=" + sensitivity +
          (attempt ? "&attempt=" + attempt : ""),
      );
    },
    results: function (jobId) {
      return call("GET", "/v1/jobs/" + encodeURIComponent(jobId) + "/results");
    },
    transcript: function (jobId, taskId, attempt, cursor) {
      return call(
        "GET",
        "/v1/jobs/" + encodeURIComponent(jobId) + "/transcript?task_id=" +
          encodeURIComponent(taskId) + "&attempt=" + attempt + "&cursor=" + (cursor || 0),
      );
    },
    report: function (jobId, format, sensitivity) {
      return call(
        "GET",
        "/v1/jobs/" + encodeURIComponent(jobId) + "/report?format=" + format +
          "&sensitivity=" + sensitivity,
      );
    },
    createDataset: function (body) {
      return call("POST", "/v1/datasets", body);
    },
    editDataset: function (datasetId, body) {
      return call("PUT", "/v1/datasets/" + encodeURIComponent(datasetId), body);
    },
    deleteDataset: function (datasetId) {
      return call("DELETE", "/v1/datasets/" + encodeURIComponent(datasetId));
    },
    createCategory: function (body) {
      return call("POST", "/v1/dataset-categories", body);
    },
    deleteCategory: function (name) {
      return call("DELETE", "/v1/dataset-categories/" + encodeURIComponent(name));
    },
  };

  // ── design system ───────────────────────────────────────────────────────

  function useStyles() {
    var token = useToken();
    return {
      token: token,
      // Surfaces
      page: { display: "flex", minHeight: "calc(100vh - 96px)", background: token.colorBgLayout },
      rail: {
        width: 216,
        flex: "0 0 216px",
        borderRight: "1px solid " + token.colorBorderSecondary,
        background: token.colorBgContainer,
        display: "flex",
        flexDirection: "column",
        padding: "18px 12px",
        position: "sticky",
        top: 0,
        alignSelf: "flex-start",
        maxHeight: "100vh",
      },
      main: {
        flex: 1,
        minWidth: 0,
        padding: "22px 26px 56px",
        display: "flex",
        flexDirection: "column",
        gap: 16,
      },
      card: {
        background: token.colorBgContainer,
        // ``colorBorderSecondary`` is nearly the layout background on a bright
        // screen, so a card drawn with it reads as one continuous sheet.  The
        // stronger border plus the host's own tertiary shadow is what makes two
        // stacked surfaces separable -- and both come from the token set, so
        // dark mode is the same code path.
        border: "1px solid " + token.colorBorder,
        borderRadius: token.borderRadiusLG,
        boxShadow: token.boxShadowTertiary,
      },
      // Type
      h1: { fontSize: 20, fontWeight: 600, color: token.colorText, lineHeight: "28px", margin: 0 },
      h2: { fontSize: 15, fontWeight: 600, color: token.colorText, margin: 0 },
      muted: { color: token.colorTextSecondary, fontSize: 12 },
      tiny: { color: token.colorTextTertiary, fontSize: 12 },
      mono: {
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
        fontSize: 12,
      },
      //: An inner surface (a row of a list, an artifact, a trace).  The fill
      //: alone is nearly white on a white card, so the border does the work.
      block: {
        background: token.colorFillQuaternary,
        border: "1px solid " + token.colorBorder,
        borderRadius: token.borderRadius,
      },
      num: { fontVariantNumeric: "tabular-nums" },
      // Layout
      row: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
      stack: { display: "flex", flexDirection: "column", gap: 12 },
      grid: {
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: 12,
      },
      sectionHead: {
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 12,
        flexWrap: "wrap",
        marginBottom: 12,
      },
    };
  }

  /** A card whose header is drawn by hand, so sections share one rhythm. */
  function Panel(props) {
    var s = useStyles();
    return h(
      "section",
      { style: Object.assign({}, s.card, props.style, { padding: props.pad === false ? 0 : 16 }) },
      props.title || props.extra
        ? h(
            "div",
            { style: Object.assign({}, s.sectionHead, { marginBottom: props.title ? 12 : 0 }) },
            h(
              "div",
              { style: { minWidth: 0 } },
              props.title ? h("div", { style: s.h2 }, props.title) : null,
              props.hint ? h("div", { style: s.tiny, marginTop: 2 }, props.hint) : null,
            ),
            props.extra || null,
          )
        : null,
      props.children,
    );
  }

  function Field(props) {
    var s = useStyles();
    return h(
      "div",
      { style: { marginBottom: props.last ? 0 : 12 } },
      h(
        "div",
        { style: Object.assign({}, s.muted, { marginBottom: 4 }) },
        props.label,
        props.hint
          ? h("span", { style: { marginLeft: 6, color: s.token.colorTextTertiary } }, props.hint)
          : null,
      ),
      props.children,
    );
  }

  function Dot(props) {
    return h("span", {
      style: {
        display: "inline-block",
        width: 7,
        height: 7,
        borderRadius: "50%",
        background: props.color,
        marginRight: 6,
        flex: "0 0 auto",
      },
    });
  }

  /** The one place a status becomes a colour, so two views cannot disagree. */
  function StatusPill(props) {
    var s = useStyles();
    var map = {
      processing: s.token.colorProcessing,
      success: s.token.colorSuccess,
      error: s.token.colorError,
      warning: s.token.colorWarning,
      blue: s.token.colorInfo,
      gold: s.token.colorWarning,
      default: s.token.colorTextTertiary,
    };
    var color = map[props.color] || s.token.colorTextTertiary;
    var text = props.text;
    if (props.taskStatus) {
      text = TASK_STATUS_TEXT[props.taskStatus] || statusMeta(props.taskStatus).text;
      if (TASK_STATUS_TEXT[props.taskStatus]) color = s.token.colorError;
    }
    return h(
      "span",
      {
        title: props.title || "",
        style: {
          display: "inline-flex",
          alignItems: "center",
          gap: 5,
          padding: "1px 8px",
          borderRadius: 999,
          fontSize: 12,
          lineHeight: "18px",
          color: color,
          background: s.token.colorFillQuaternary,
          border: "1px solid " + s.token.colorBorderSecondary,
          whiteSpace: "nowrap",
        },
      },
      h(Dot, { color: color }),
      text,
    );
  }

  function StatCard(props) {
    var s = useStyles();
    return h(
      "div",
      { style: Object.assign({}, s.card, { padding: "14px 16px", minWidth: 0 }) },
      h("div", { style: s.muted }, props.label),
      h(
        "div",
        {
          style: Object.assign({}, s.num, {
            fontSize: 24,
            fontWeight: 600,
            lineHeight: "32px",
            color: props.color || s.token.colorText,
            marginTop: 2,
          }),
        },
        props.value,
      ),
      props.hint ? h("div", { style: Object.assign({}, s.tiny, { marginTop: 2 }) }, props.hint) : null,
    );
  }

  /** One of the four numbers across the top of a report, with an optional bar. */
  function ReportMetric(props) {
    var s = useStyles();
    return h(
      "div",
      {
        style: {
          padding: "0 14px",
          borderLeft: "1px solid " + s.token.colorBorderSecondary,
          minWidth: 0,
        },
      },
      h("div", { style: s.tiny }, props.label),
      h(
        "div",
        { style: Object.assign({}, s.num, { fontSize: 23, fontWeight: 600, lineHeight: "30px" }) },
        props.value,
      ),
      props.bar ? props.bar : h("div", { style: s.tiny }, props.hint || ""),
    );
  }

  function ScoreText(props) {
    var s = useStyles();
    var value = props.value;
    if (value === null || value === undefined) {
      return h("span", { style: Object.assign({}, s.tiny, s.num) }, "—");
    }
    var color =
      value >= 0.8 ? s.token.colorSuccess : value >= 0.5 ? s.token.colorWarning : s.token.colorError;
    return h(
      "span",
      { style: Object.assign({}, s.num, { color: color, fontWeight: props.bold ? 600 : 400 }) },
      fmtNum(value, 3),
    );
  }

  /** A tiny bar under a number: reads as "how full" without a tooltip. */
  function MiniBar(props) {
    var s = useStyles();
    var percent = Math.max(0, Math.min(100, Math.round((Number(props.percent) || 0) * 100)));
    var color = props.color || s.token.colorPrimary;
    return h(
      "div",
      {
        style: {
          height: 6,
          borderRadius: 3,
          background: s.token.colorFill,
          overflow: "hidden",
          minWidth: 48,
        },
      },
      h("div", { style: { width: percent + "%", height: "100%", background: color } }),
    );
  }

  /** An id a reader will want to paste into a log search. */
  function CopyId(props) {
    var s = useStyles();
    var value = props.value || "";
    if (!value) return h("span", { style: s.tiny }, "—");
    return h(
      "span",
      { style: Object.assign({}, s.row, { gap: 4, flexWrap: "nowrap" }) },
      h("code", { style: Object.assign({}, s.mono, { color: s.token.colorText }) }, props.full ? value : value.slice(0, 12)),
      h(
        Button,
        {
          size: "small",
          type: "text",
          style: { padding: "0 4px", height: 18 },
          onClick: function (event) {
            if (event && event.stopPropagation) event.stopPropagation();
            copyText(value, props.label || "已复制");
          },
        },
        "复制",
      ),
    );
  }

  function EmptyState(props) {
    var s = useStyles();
    return h(
      "div",
      { style: { padding: "48px 16px", textAlign: "center" } },
      h("div", { style: { fontSize: 30, lineHeight: "40px", marginBottom: 8 } }, props.glyph || "◇"),
      h("div", { style: { fontSize: 14, color: s.token.colorText, marginBottom: 4 } }, props.title),
      h("div", { style: Object.assign({}, s.muted, { margin: "0 auto 14px", maxWidth: 420 }) }, props.hint),
      props.action || null,
    );
  }

  function NavItem(props) {
    var s = useStyles();
    var active = props.active;
    return h(
      "button",
      {
        type: "button",
        onClick: props.onClick,
        style: {
          display: "flex",
          alignItems: "center",
          gap: 10,
          width: "100%",
          padding: "9px 10px",
          border: "none",
          borderRadius: s.token.borderRadius,
          background: active ? s.token.colorPrimaryBg : "transparent",
          color: active ? s.token.colorPrimary : s.token.colorText,
          fontWeight: active ? 600 : 400,
          fontSize: 13,
          cursor: "pointer",
          textAlign: "left",
        },
      },
      h("span", { style: { width: 18, textAlign: "center", opacity: active ? 1 : 0.75 } }, props.glyph),
      h("span", { style: { flex: 1 } }, props.label),
      props.badge
        ? h(
            "span",
            {
              style: {
                fontSize: 11,
                padding: "0 6px",
                borderRadius: 999,
                background: s.token.colorFillSecondary,
                color: s.token.colorTextSecondary,
              },
            },
            props.badge,
          )
        : null,
    );
  }

  // ── dataset picker + resolve ────────────────────────────────────────────

  function SelectorPanel(props) {
    var s = useStyles();
    if (props.loading) {
      return h("div", { style: Object.assign({}, s.card, { padding: 12 }) },
        h(Spin, { size: "small" }), " 正在解析选择…");
    }
    if (props.error) {
      return h(Alert, {
        type: "error",
        showIcon: true,
        message: "解析失败：" + props.error.code,
        description: props.error.message,
      });
    }
    var res = props.resolved;
    if (!res) {
      return h(
        "div",
        { style: Object.assign({}, s.card, { padding: 14, background: s.token.colorFillQuaternary }) },
        h("div", { style: s.muted }, "选定分类或数据集后，这里显示这次会跑到哪些题。"),
      );
    }
    var bySource = res.by_dataset || {};
    return h(
      "div",
      { style: Object.assign({}, s.card, { padding: 14 }) },
      h(
        "div",
        { style: s.row },
        h("span", { style: { fontSize: 22, fontWeight: 600 } }, res.task_count),
        h("span", { style: s.muted }, "道题"),
        h("span", { style: s.tiny }, "摘要 " + (res.task_ids_digest || "")),
      ),
      Object.keys(bySource).length
        ? h(
            "div",
            { style: Object.assign({}, s.row, { marginTop: 6 }) },
            h("span", { style: s.tiny }, "按来源："),
            Object.keys(bySource).map(function (key) {
              return h(Tag, { key: key, bordered: false }, key + " " + bySource[key]);
            }),
          )
        : null,
      Object.keys(res.by_category || {}).length
        ? h(
            "div",
            { style: Object.assign({}, s.row, { marginTop: 4 }) },
            h("span", { style: s.tiny }, "分类展开："),
            Object.keys(res.by_category).map(function (key) {
              return h(Tag, { key: key, bordered: false }, key + " " + res.by_category[key]);
            }),
          )
        : null,
      (res.task_ids || []).length
        ? h(
            "details",
            { style: { marginTop: 8 } },
            h("summary", { style: Object.assign({}, s.tiny, { cursor: "pointer" }) },
              "题目清单（前 40 条）"),
            h(
              "div",
              { style: Object.assign({}, s.mono, { marginTop: 6, maxHeight: 160, overflow: "auto" }) },
              (res.task_ids || []).slice(0, 40).map(function (id) {
                return h("div", { key: id }, id);
              }),
            ),
          )
        : null,
    );
  }

  // ── module: jobs list ───────────────────────────────────────────────────

  function JobsModule(props) {
    var s = useStyles();
    var jobs = props.jobs || [];
    var [status, setStatus] = useState("all");
    var [query, setQuery] = useState("");
    var [busy, setBusy] = useState("");

    var waiting = useMemo(function () {
      return jobs
        .filter(function (job) {
          return ORDERABLE[job.status];
        })
        .sort(function (a, b) {
          return a.queue_pos - b.queue_pos;
        });
    }, [jobs]);

    var stats = useMemo(
      function () {
        var running = 0;
        var done = 0;
        var scores = [];
        jobs.forEach(function (job) {
          if (job.status === "running") running += 1;
          if (job.status === "finished") done += 1;
          if (typeof job.score === "number") scores.push(job.score);
        });
        var mean = scores.length
          ? scores.reduce(function (a, b) {
              return a + b;
            }, 0) / scores.length
          : null;
        return { running: running, waiting: waiting.length, done: done, mean: mean, total: jobs.length };
      },
      [jobs, waiting],
    );

    var rows = useMemo(
      function () {
        var needle = query.trim().toLowerCase();
        return jobs
          .filter(function (job) {
            if (status === "running" && job.status !== "running") return false;
            if (status === "waiting" && !ORDERABLE[job.status]) return false;
            if (status === "done" && !TERMINAL[job.status]) return false;
            if (!needle) return true;
            return [job.job_id, job.purpose, job.product, job.submitter, job.acp_url]
              .join(" ")
              .toLowerCase()
              .indexOf(needle) >= 0;
          })
          .sort(function (a, b) {
            // Waiting first in queue order, then everything else newest first:
            // the two questions this list answers are "what runs next" and
            // "what did I just do".
            var aWaiting = ORDERABLE[a.status] ? 0 : 1;
            var bWaiting = ORDERABLE[b.status] ? 0 : 1;
            if (aWaiting !== bWaiting) return aWaiting - bWaiting;
            if (aWaiting === 0) return a.queue_pos - b.queue_pos;
            return String(b.created_at || "").localeCompare(String(a.created_at || ""));
          });
      },
      [jobs, status, query],
    );

    function move(job, direction) {
      var index = waiting.indexOf(job);
      var target = null;
      if (direction === "up") {
        var previous = waiting[index - 1];
        if (previous) target = { before_id: previous.job_id };
      } else {
        var next = waiting[index + 1];
        if (next) target = { after_id: next.job_id };
      }
      if (!target) return;
      setBusy(job.job_id);
      api
        .reorder(job.job_id, target)
        .then(function () {
          return props.onRefresh();
        })
        .catch(function (err) {
          message.error("调序被拒：" + errOf(err).message);
          return props.onRefresh();
        })
        .then(function () {
          setBusy("");
        });
    }

    function cancel(job) {
      setBusy(job.job_id);
      api
        .cancel(job.job_id, "")
        .then(function () {
          message.success("已取消");
          return props.onRefresh();
        })
        .catch(function (err) {
          message.error("取消失败：" + errOf(err).message);
          return props.onRefresh();
        })
        .then(function () {
          setBusy("");
        });
    }

    var columns = [
      {
        title: "状态",
        dataIndex: "status",
        width: 100,
        render: function (value, row) {
          var meta = statusMeta(value);
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column", gap: 4 } },
            h(StatusPill, { text: meta.text, color: meta.color }),
            value === "queued" || value === "scheduled"
              ? h("span", { style: s.tiny }, "位置 " + fmtNum(row.queue_pos, 0))
              : null,
          );
        },
      },
      {
        title: "评测",
        dataIndex: "purpose",
        render: function (_, job) {
          var mine = props.subject && job.submitter === props.subject;
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column", gap: 2, minWidth: 0 } },
            h(
              "div",
              { style: s.row },
              h(Text, { strong: true }, job.purpose || "（未写目的）"),
              mine ? h(Tag, { color: "blue", bordered: false }, "我的") : null,
            ),
            h(
              "div",
              { style: Object.assign({}, s.row, { gap: 6 }) },
              h("span", { style: s.mono }, shortId(job.job_id)),
              job.product ? h("span", { style: s.tiny }, job.product) : null,
              job.acp_url
                ? h("span", {
                    style: Object.assign({}, s.tiny, {
                      maxWidth: 260,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }),
                    title: job.acp_url,
                  }, job.acp_url)
                : null,
            ),
          );
        },
      },
      {
        title: "题目",
        width: 150,
        render: function (_, job) {
          var total = Number(job.task_count) || 0;
          var finished = Number(job.tasks_finished) || 0;
          var failed = Number(job.tasks_failed) || 0;
          if (!total) return h("span", { style: s.tiny }, "—");
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column", gap: 4 } },
            h(
              "div",
              { style: Object.assign({}, s.row, { gap: 4 }) },
              h("span", { style: Object.assign({}, s.num, { fontSize: 12 }) }, finished + " / " + total),
              failed ? h("span", { style: { fontSize: 12, color: s.token.colorError } }, "败 " + failed) : null,
            ),
            h(Progress, {
              percent: total ? Math.round((finished / total) * 100) : 0,
              size: "small",
              showInfo: false,
              status: "normal",
              strokeColor: failed ? s.token.colorError : s.token.colorPrimary,
            }),
          );
        },
      },
      {
        title: "分数",
        dataIndex: "score",
        width: 92,
        render: function (value) {
          return h(ScoreText, { value: value, bold: true });
        },
      },
      { title: "提交人", dataIndex: "submitter", width: 100 },
      {
        title: "时间",
        dataIndex: "created_at",
        width: 132,
        render: function (_, job) {
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column" } },
            h("span", { style: { fontSize: 12 } }, fmtShort(job.created_at)),
            h("span", { style: s.tiny },
              TERMINAL[job.status] ? "结束 " + fmtShort(job.finished_at) : untilText(job.not_before)),
          );
        },
      },
      {
        title: "",
        width: 168,
        render: function (_, job) {
          var mine = !props.subject || job.submitter === props.subject;
          var movable = ORDERABLE[job.status] && mine;
          var index = waiting.indexOf(job);
          return h(
            Space,
            { size: 2 },
            movable
              ? h(
                  Tooltip,
                  { title: "上移一位" },
                  h(Button, {
                    size: "small",
                    type: "text",
                    disabled: index <= 0 || busy === job.job_id,
                    onClick: function (event) {
                      event.stopPropagation();
                      move(job, "up");
                    },
                  }, "↑"),
                )
              : null,
            movable
              ? h(
                  Tooltip,
                  { title: "下移一位" },
                  h(Button, {
                    size: "small",
                    type: "text",
                    disabled: index >= waiting.length - 1 || busy === job.job_id,
                    onClick: function (event) {
                      event.stopPropagation();
                      move(job, "down");
                    },
                  }, "↓"),
                )
              : null,
            TERMINAL[job.status]
              ? h(
                  Button,
                  {
                    size: "small",
                    type: "link",
                    onClick: function (event) {
                      event.stopPropagation();
                      props.onOpen(job.job_id);
                    },
                  },
                  "报告",
                )
              : h(
                  Popconfirm,
                  {
                    title: "取消这个评测？",
                    description:
                      job.status === "running"
                        ? "运行中的会话会被停掉，已跑完的题保留。"
                        : "取消后不能恢复。",
                    okText: "取消评测",
                    cancelText: "算了",
                    onConfirm: function () {
                      cancel(job);
                    },
                  },
                  h(
                    Button,
                    { size: "small", type: "text", danger: true, loading: busy === job.job_id },
                    "取消",
                  ),
                ),
            h(
              Button,
              {
                size: "small",
                type: "text",
                onClick: function (event) {
                  event.stopPropagation();
                  props.onOpen(job.job_id);
                },
              },
              "详情",
            ),
          );
        },
      },
    ];

    return h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 16 } },
      h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 } },
        h(StatCard, { label: "运行中", value: stats.running, hint: stats.running ? "占着并发槽" : "当前空闲" }),
        h(StatCard, { label: "等待中", value: stats.waiting, hint: stats.waiting ? "可调序" : "队列为空" }),
        h(StatCard, { label: "已完成", value: stats.done, hint: "全部 " + stats.total + " 次提交" }),
        h(StatCard, {
          label: "平均分",
          value: stats.mean === null ? "—" : fmtPct(stats.mean),
          color: stats.mean === null ? undefined : stats.mean >= 0.8 ? s.token.colorSuccess : undefined,
          hint: "有分数的评测",
        }),
      ),
      h(
        Panel,
        {
          pad: false,
          title: null,
          children: h(
            "div",
            null,
            h(
              "div",
              { style: Object.assign({}, s.sectionHead, { padding: "14px 16px", marginBottom: 0 }) },
              h(
                "div",
                { style: s.row },
                h(Segmented, {
                  size: "small",
                  value: status,
                  onChange: setStatus,
                  options: [
                    { value: "all", label: "全部" },
                    { value: "running", label: "运行中" },
                    { value: "waiting", label: "等待中" },
                    { value: "done", label: "已结束" },
                  ],
                }),
                h(Input, {
                  allowClear: true,
                  size: "small",
                  placeholder: "搜目的、job id、产品、提交人",
                  style: { width: 240 },
                  value: query,
                  onChange: function (event) {
                    setQuery(event.target.value);
                  },
                }),
              ),
              h(
                "div",
                { style: s.row },
                h(Button, { size: "small", onClick: props.onRefresh }, "刷新"),
                h(
                  Button,
                  { size: "small", type: "primary", onClick: props.onNew },
                  "＋ 新建评测",
                ),
              ),
            ),
            h(Table, {
              size: "middle",
              rowKey: "job_id",
              dataSource: rows,
              columns: columns,
              pagination: rows.length > 12 ? { pageSize: 12, size: "small" } : false,
              scroll: { x: 1040 },
              onHeaderRow: function () {
                return { style: { background: s.token.colorFillQuaternary } };
              },
              onRow: function (job) {
                return {
                  onClick: function () {
                    props.onOpen(job.job_id);
                  },
                  style: { cursor: "pointer" },
                };
              },
              locale: {
                emptyText: h(EmptyState, {
                  glyph: "🧪",
                  title: jobs.length ? "这个筛选下没有评测" : "还没有评测",
                  hint: jobs.length
                    ? "换个筛选条件，或者清空搜索词。"
                    : "点右上角「新建评测」，填一个 ACP 地址和要跑的题就能排队。",
                  action: jobs.length
                    ? null
                    : h(Button, { type: "primary", onClick: props.onNew }, "新建评测"),
                }),
              },
            }),
          ),
        },
      ),
    );
  }

  // ── modal: new job ──────────────────────────────────────────────────────

  function NewJobModal(props) {
    var s = useStyles();
    var catalog = props.catalog || { datasets: [], categories: [] };
    var [acpUrl, setAcpUrl] = useState(readLS("acpUrl", ""));
    var [product, setProduct] = useState(readLS("product", "qwenpaw-desktop"));
    var [purpose, setPurpose] = useState("");
    var [datasetIds, setDatasetIds] = useState([]);
    var [categoryNames, setCategoryNames] = useState([]);
    var [kind, setKind] = useState("immediate");
    var [start, setStart] = useState("");
    var [end, setEnd] = useState("");
    var [resolved, setResolved] = useState(null);
    var [resolving, setResolving] = useState(false);
    var [resolveError, setResolveError] = useState(null);
    var [submitting, setSubmitting] = useState(false);
    var [receipt, setReceipt] = useState(null);
    var [serviceZone, setServiceZone] = useState(readLS("serviceZone", ""));

    var selector = useMemo(
      function () {
        return { datasets: datasetIds, categories: categoryNames };
      },
      [datasetIds, categoryNames],
    );
    var selectorEmpty = datasetIds.length === 0 && categoryNames.length === 0;

    // A fresh modal is a fresh submission: the previous receipt would otherwise
    // read as this one's result.
    useEffect(
      function () {
        if (props.open) return;
        setReceipt(null);
        setSubmitting(false);
      },
      [props.open],
    );

    useEffect(
      function () {
        if (selectorEmpty) {
          setResolved(null);
          setResolveError(null);
          return undefined;
        }
        var alive = true;
        setResolving(true);
        var timer = setTimeout(function () {
          api
            .resolve(selector)
            .then(function (result) {
              if (!alive) return;
              setResolved(result);
              setResolveError(null);
            })
            .catch(function (err) {
              if (!alive) return;
              setResolved(null);
              setResolveError(errOf(err));
            })
            .then(function () {
              if (alive) setResolving(false);
            });
        }, 250);
        return function () {
          alive = false;
          clearTimeout(timer);
        };
      },
      [selector, selectorEmpty],
    );

    function isoFromPick(value) {
      if (!value) return "";
      var parsed = new Date(value.replace(" ", "T"));
      return isNaN(parsed.getTime()) ? "" : parsed.toISOString();
    }

    var customStart = isoFromPick(start);
    var customEnd = isoFromPick(end);
    var windowProblem = null;
    if (kind === "custom") {
      if (!customStart || !customEnd) windowProblem = "自定义区间要填开始和结束两个时间";
      else if (new Date(customEnd) <= new Date(customStart)) windowProblem = "结束时间必须晚于开始时间";
      else if (new Date(customStart) < new Date()) windowProblem = "开始时间已经在过去";
    }
    var canSubmit =
      !submitting && acpUrl.trim() && !selectorEmpty && resolved && !resolving && !windowProblem;

    function submit() {
      setSubmitting(true);
      setReceipt(null);
      var body = {
        acp_url: acpUrl.trim(),
        selector: selector,
        product: product.trim(),
        purpose: purpose.trim(),
        window:
          kind === "custom"
            ? { kind: "custom", not_before: customStart, not_after: customEnd }
            : { kind: kind },
      };
      api
        .submit(body)
        .then(function (result) {
          writeLS("acpUrl", acpUrl.trim());
          writeLS("product", product.trim());
          if (result.window && result.window.tz) {
            setServiceZone(result.window.tz);
            writeLS("serviceZone", result.window.tz);
          }
          message.success("已排队，位置 " + fmtNum(result.queue_pos, 1));
          if (props.onSubmitted) props.onSubmitted(result);
          // The service has no "who am I" route; the row this job wrote does.
          return api
            .learnIdentity(result.job_id)
            .then(function (identity) {
              if (identity && identity.subject && props.onIdentity) {
                props.onIdentity(identity.subject);
              }
            })
            .catch(function () {
              /* identity is a nicety, never a reason to fail a submission */
            });
        })
        .catch(function (err) {
          setReceipt({ error: errOf(err) });
        })
        .then(function () {
          setSubmitting(false);
        });
    }

    var datasetOptions = (catalog.datasets || []).map(function (entry) {
      var unfiled = !entry.categories || entry.categories.length === 0;
      return {
        value: entry.id,
        label: entry.name + " · " + entry.task_count + " 题" + (unfiled ? "（未分类）" : ""),
      };
    });
    var categoryOptions = (catalog.categories || []).map(function (entry) {
      return { value: entry.name, label: entry.name + " · " + (entry.dataset_count || 0) + " 个数据集" };
    });

    return h(
      Modal,
      {
        open: props.open,
        onCancel: props.onClose,
        title: h(
          "div",
          { style: { display: "flex", flexDirection: "column", gap: 2 } },
          h("span", { style: { fontSize: 16, fontWeight: 600 } }, "新建评测"),
          h("span", { style: s.tiny }, "填一个被评测端的 ACP 地址，选题，然后排队"),
        ),
        width: 820,
        style: { top: 32 },
        footer: h(
          "div",
          { style: Object.assign({}, s.row, { justifyContent: "space-between" }) },
          h(
            "span",
            { style: s.tiny },
            resolved
              ? "将跑 " + resolved.task_count + " 道题 · 摘要 " + (resolved.task_ids_digest || "")
              : "选题后显示题量",
          ),
          h(
            Space,
            null,
            h(Button, { onClick: props.onClose }, "取消"),
            h(
              Button,
              { type: "primary", loading: submitting, disabled: !canSubmit, onClick: submit },
              "提交排队",
            ),
          ),
        ),
      },
      h(
        "div",
        { style: { display: "flex", flexDirection: "column", gap: 14 } },
        h(
          "div",
          { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 12 } },
          h(
            Field,
            { label: "ACP 地址", hint: "被评测端", last: true },
            h(Input, {
              value: acpUrl,
              placeholder: "http://127.0.0.1:8765",
              onChange: function (event) {
                setAcpUrl(event.target.value);
              },
            }),
          ),
          h(
            Field,
            { label: "评测产品", last: true },
            h(Input, {
              value: product,
              placeholder: "qwenpaw-desktop",
              onChange: function (event) {
                setProduct(event.target.value);
              },
            }),
          ),
          h(
            Field,
            { label: "评测目的", hint: "给自己看的", last: true },
            h(Input, {
              value: purpose,
              placeholder: "夜间冒烟 / 回归 / 发版前",
              onChange: function (event) {
                setPurpose(event.target.value);
              },
            }),
          ),
        ),
        h("div", { style: { height: 1, background: s.token.colorBorderSecondary } }),
        h(
          "div",
          { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 12 } },
          h(
            Field,
            { label: "分类（整组）", hint: "与数据集混选", last: true },
            h(Select, {
              mode: "multiple",
              allowClear: true,
              style: { width: "100%" },
              placeholder: "按分类整组加入",
              value: categoryNames,
              options: categoryOptions,
              onChange: setCategoryNames,
            }),
          ),
          h(
            Field,
            { label: "数据集", last: true },
            h(Select, {
              mode: "multiple",
              allowClear: true,
              style: { width: "100%" },
              placeholder: "挑具体的数据集",
              value: datasetIds,
              options: datasetOptions,
              onChange: setDatasetIds,
            }),
          ),
        ),
        selectorEmpty
          ? h(
              "div",
              { style: Object.assign({}, s.card, { padding: 14, background: s.token.colorFillQuaternary }) },
              h("div", { style: s.muted }, "还没有选题。先选一个数据集或分类，这里会显示题量与题目清单。"),
            )
          : h(SelectorPanel, { resolved: resolved, loading: resolving, error: resolveError }),
        h("div", { style: { height: 1, background: s.token.colorBorderSecondary } }),
        h(
          "div",
          { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(230px, 1fr))", gap: 12 } },
          h(
            Field,
            { label: "可运行时间", last: true },
            h(Segmented, {
              value: kind,
              onChange: setKind,
              options: [
                { value: "immediate", label: "即时" },
                { value: "night", label: "夜间" },
                { value: "custom", label: "自定义" },
              ],
            }),
          ),
          kind === "custom"
            ? h(
                Field,
                { label: "开始（本地）", last: true },
                h(DatePicker, {
                  showTime: { format: "HH:mm" },
                  format: "YYYY-MM-DD HH:mm",
                  placeholder: "选择日期时间",
                  style: { width: "100%" },
                  onChange: function (_, text) {
                    setStart(text);
                  },
                }),
              )
            : null,
          kind === "custom"
            ? h(
                Field,
                { label: "结束（本地）", last: true },
                h(DatePicker, {
                  showTime: { format: "HH:mm" },
                  format: "YYYY-MM-DD HH:mm",
                  placeholder: "选择日期时间",
                  style: { width: "100%" },
                  onChange: function (_, text) {
                    setEnd(text);
                  },
                }),
              )
            : null,
        ),
        kind === "night"
          ? h(Alert, {
              type: "info",
              showIcon: true,
              message: "夜间窗口由服务的 schedule.night_window 决定，提交后回填区间。",
            })
          : null,
        h(
          "div",
          { style: Object.assign({}, s.row, { gap: 16 }, s.tiny) },
          h("span", null, "本地 " + localZone() + " " + offsetLabel(new Date())),
          h("span", null, "服务 " + (serviceZone || "未知（提交后回填）")),
          customStart ? h("span", null, "起跑 " + fmtFull(customStart) + " / " + fmtUtc(customStart) + " UTC") : null,
        ),
        windowProblem ? h(Alert, { type: "warning", showIcon: true, message: windowProblem }) : null,
        receipt && receipt.error
          ? h(Alert, {
              type: "error",
              showIcon: true,
              message: "提交被拒：" + receipt.error.code,
              description: h(
                "div",
                null,
                h("div", null, receipt.error.message),
                receipt.error.details
                  ? h(
                      "pre",
                      { style: Object.assign({}, s.mono, { margin: "6px 0 0", whiteSpace: "pre-wrap" }) },
                      JSON.stringify(receipt.error.details, null, 1),
                    )
                  : null,
              ),
            })
          : null,
      ),
    );
  }

  // ── module: one report ──────────────────────────────────────────────────

  /** A score in a ring, with the denominator spelled out underneath. */
  function ScoreDial(props) {
    var s = useStyles();
    var score = props.score;
    if (score === null || score === undefined) {
      return h(
        "div",
        { style: { textAlign: "center" } },
        h("div", { style: Object.assign({}, s.num, { fontSize: 34, fontWeight: 600, color: s.token.colorTextTertiary }) }, "—"),
        h("div", { style: s.tiny }, "没有计分题"),
      );
    }
    var color =
      score >= 0.8 ? s.token.colorSuccess : score >= 0.5 ? s.token.colorWarning : s.token.colorError;
    return h(
      "div",
      { style: { textAlign: "center" } },
      h(Progress, {
        type: "dashboard",
        percent: Math.round(score * 1000) / 10,
        size: 132,
        strokeColor: color,
        trailColor: s.token.colorFillSecondary,
        format: function () {
          return h(
            "span",
            { style: Object.assign({}, s.num, { fontSize: 26, fontWeight: 600, color: color }) },
            fmtNum(score, 3),
          );
        },
      }),
      h("div", { style: s.tiny }, props.caption || ""),
    );
  }

  function SliceBars(props) {
    var s = useStyles();
    var entries = Object.keys(props.data || {});
    if (!entries.length) return h("span", { style: s.tiny }, "暂无可用切片");
    var rows = entries
      .map(function (name) {
        return { name: name, value: props.data[name] };
      })
      .sort(function (a, b) {
        return Number(b.value) - Number(a.value);
      });
    return h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 6 } },
      rows.map(function (row) {
        return h(
          "div",
          { key: row.name, style: { display: "flex", alignItems: "center", gap: 10 } },
          h("span", { style: Object.assign({ width: 168, flex: "0 0 168px" }, s.tiny), title: row.name }, row.name),
          h(
            "div",
            { style: { flex: 1, minWidth: 80 } },
            h(Progress, {
              percent: Math.round((Number(row.value) || 0) * 100),
              size: "small",
              showInfo: false,
              status: "normal",
              strokeColor: s.token.colorPrimary,
            }),
          ),
          h(
            "span",
            { style: Object.assign({ width: 52, textAlign: "right", flex: "0 0 52px" }, s.num) },
            h(ScoreText, { value: row.value }),
          ),
        );
      }),
    );
  }

  function Fact(props) {
    var s = useStyles();
    return h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 2, minWidth: 0 } },
      h("span", { style: s.tiny }, props.label),
      h("span", { style: { fontSize: 13, color: s.token.colorText, wordBreak: "break-word" } }, props.children),
    );
  }

  function BrokenDown(props) {
    var s = useStyles();
    var entries = Object.keys(props.data || {});
    if (!entries.length) return h("span", { style: s.tiny }, "没有逐项判分（非规则判分或未产出）");
    return h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 6 } },
      entries.map(function (name) {
        var value = Number(props.data[name]);
        var ok = value >= 1;
        return h(
          "div",
          {
            key: name,
            style: Object.assign({}, s.block, {
              display: "flex",
              alignItems: "center",
              gap: 8,
              padding: "6px 10px",
            }),
          },
          h(
            "span",
            {
              style: {
                width: 18,
                textAlign: "center",
                color: ok ? s.token.colorSuccess : s.token.colorError,
                fontWeight: 600,
              },
            },
            ok ? "✓" : "✗",
          ),
          h("span", { style: Object.assign({ flex: 1 }, s.mono) }, name),
          h(
            "span",
            {
              style: Object.assign({}, s.mono, s.num, {
                color: ok ? s.token.colorSuccess : s.token.colorError,
              }),
            },
            fmtNum(value, 3),
          ),
        );
      }),
    );
  }

  /** The event stream, one row per line, with the kind translated. */
  function Timeline(props) {
    var s = useStyles();
    var events = props.events || [];
    if (!events.length) {
      return h("span", { style: s.tiny }, props.hint || "这次运行没有可读的轨迹");
    }
    var KIND = {
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
    return h(
      "div",
      {
        style: {
          display: "flex",
          flexDirection: "column",
          maxHeight: 340,
          overflow: "auto",
          border: "1px solid " + s.token.colorBorder,
          borderRadius: s.token.borderRadius,
        },
      },
      events.map(function (event, index) {
        var text = KIND[event.kind] || event.kind;
        var accent =
          event.kind === "tool_call" || event.kind === "tool_call_update"
            ? s.token.colorInfo
            : s.token.colorTextTertiary;
        return h(
          "div",
          {
            key: index,
            style: {
              display: "flex",
              alignItems: "baseline",
              gap: 10,
              padding: "5px 10px",
              borderTop: index ? "1px solid " + s.token.colorBorderSecondary : "none",
              fontSize: 12,
            },
          },
          h("span", { style: Object.assign({ width: 62, flex: "0 0 62px" }, s.tiny, s.num) },
            event.at ? fmtFull(event.at).slice(11) : ""),
          h("span", { style: { width: 34, flex: "0 0 34px", color: accent } }, text),
          h(
            "span",
            { style: { flex: 1, minWidth: 0, wordBreak: "break-word" } },
            event.tool ? h("strong", { style: { fontWeight: 600 } }, event.tool) : null,
            event.status ? h("span", { style: s.tiny }, " · " + event.status) : null,
            event.args && Object.keys(event.args).length
              ? h("span", { style: s.tiny }, " · " + Object.keys(event.args).join(", "))
              : null,
            event.steps ? h("span", { style: s.tiny }, " · " + event.steps + " 步计划") : null,
            event.chars ? h("span", { style: s.tiny }, " · " + event.chars + " 字符") : null,
            event.result_chars ? h("span", { style: s.tiny }, " · 结果 " + event.result_chars + " 字符") : null,
          ),
        );
      }),
    );
  }

  function TaskPanel(props) {
    var s = useStyles();
    var jobId = props.jobId;
    var task = props.task;
    var [expanded, setExpanded] = useState(false);
    var [transcript, setTranscript] = useState(null);
    var [loadingMore, setLoadingMore] = useState(false);
    var attempt = task.attempt || 1;

    useEffect(
      function () {
        if (!task) return undefined;
        var alive = true;
        setTranscript(null);
        api
          .transcript(jobId, task.task_id, attempt, 0)
          .then(function (page) {
            if (alive) setTranscript(page);
          })
          .catch(function (err) {
            if (alive) message.error("轨迹读取失败：" + errOf(err).message);
          });
        return function () {
          alive = false;
        };
      },
      [jobId, task && task.task_id, attempt],
    );

    if (!task) return null;

    function more() {
      if (!transcript || transcript.next_cursor === null) return;
      setLoadingMore(true);
      api
        .transcript(jobId, task.task_id, attempt, transcript.next_cursor)
        .then(function (page) {
          setTranscript(function (previous) {
            return Object.assign({}, page, {
              events: ((previous && previous.events) || []).concat(page.events || []),
            });
          });
        })
        .catch(function (err) {
          message.error("轨迹翻页失败：" + errOf(err).message);
        })
        .then(function () {
          setLoadingMore(false);
        });
    }

    var prompt = String(task.prompt || "");
    var downloads = task.downloads || [];
    var full = props.sensitivity === "full";

    return h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 14 } },
      h(
        "div",
        { style: s.row },
        h(Button, { size: "small", onClick: props.onBack }, "← 返回题目列表"),
        h("span", { style: { fontSize: 15, fontWeight: 600 } }, task.name || task.task_id),
        h(StatusPill, { taskStatus: task.status, text: statusMeta(task.status).text }),
        h("span", { style: s.tiny }, "第 " + attempt + " 次 · " + fmtDuration(task.duration_s)),
        h("span", { style: s.row }, h("span", { style: s.tiny }, "分数"), h(ScoreText, { value: task.score, bold: true })),
      ),
      task.failure_reason
        ? h(Alert, { type: "error", showIcon: true, message: "失败原因：" + task.failure_reason })
        : null,
      h(
        Panel,
        { title: "题干", hint: "评测时发给 agent 的原文" },
        prompt
          ? h(
              "div",
              {
                style: Object.assign({}, s.mono, {
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.7,
                  maxHeight: expanded ? "none" : 280,
                  overflow: "auto",
                  background: s.token.colorFillQuaternary,
                  border: "1px solid " + s.token.colorBorder,
                  padding: 12,
                  borderRadius: s.token.borderRadius,
                }),
              },
              prompt,
            )
          : h("span", { style: s.tiny }, "这道题没有留下题干（数据集里没有 task 正文）"),
        prompt.length > 600
          ? h(
              Button,
              {
                size: "small",
                type: "link",
                style: { paddingLeft: 0, marginTop: 6 },
                onClick: function () {
                  setExpanded(!expanded);
                },
              },
              expanded ? "收起" : "展开全部（" + prompt.length + " 字符）",
            )
          : null,
      ),
      h(
        Panel,
        { title: "这次执行", hint: "trace 与 session 是回到日志的入口" },
        h(
          "div",
          { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))", gap: 12 } },
          h(Fact, { label: "判分方式" }, task.grading_type || "—"),
          h(Fact, { label: "耗时" }, fmtDuration(task.duration_s)),
          h(Fact, { label: "写回" },
            "协议 " + (task.protocol_written || 0) + " · 带外 " + (task.out_of_band_count || 0)),
          h(Fact, { label: "自报模型" }, (task.subject_model_reported || []).join("、") || "—"),
          h(Fact, { label: "trace_id" }, h(CopyId, { value: task.trace_id, label: "trace_id 已复制" })),
          h(Fact, { label: "session_id" }, h(CopyId, { value: task.session_id, label: "session_id 已复制" })),
          h(Fact, { label: "解析自" }, (task.resolved_from || []).join("、") || "—"),
          h(Fact, { label: "尝试" }, "第 " + attempt + " 次"),
        ),
      ),
      h(
        Panel,
        { title: "判据逐项", hint: task.grading_type === "llm_judge" ? "LLM 判分不产出逐项" : "" },
        h(BrokenDown, { data: task.automated_breakdown }),
      ),
      h(
        Panel,
        { title: "产物", hint: full ? "可下载" : "shared 档只列清单，下载需切到完整版" },
        (task.artifacts || []).length
          ? h(
              "div",
              { style: { display: "flex", flexDirection: "column", gap: 6 } },
              (task.artifacts || []).map(function (item) {
                var link = downloads.filter(function (entry) {
                  return entry.path === item.path;
                })[0];
                return h(
                  "div",
                  {
                    key: item.path,
                    style: Object.assign({}, s.block, s.row, {
                      justifyContent: "space-between",
                      padding: "6px 10px",
                    }),
                  },
                  h(
                    "div",
                    { style: Object.assign({}, s.row, { gap: 8, minWidth: 0 }) },
                    h("code", { style: s.mono }, item.path),
                    h("span", { style: s.tiny }, item.size + " B · " + String(item.sha256).slice(0, 12)),
                  ),
                  link
                    ? h(
                        Button,
                        {
                          size: "small",
                          type: "link",
                          onClick: function () {
                            downloadPath(
                              link.href + "?path=" + encodeURIComponent(link.query.path),
                              item.path.split("/").pop(),
                            );
                          },
                        },
                        "下载",
                      )
                    : null,
                );
              }),
            )
          : h("span", { style: s.tiny }, "没有产物"),
      ),
      full
        ? h(
            Panel,
            { title: "评分依据（完整版）", pad: true },
            h(
              "div",
              { style: { display: "flex", flexDirection: "column", gap: 12 } },
              task.rubric_excerpt
                ? h(
                    "div",
                    null,
                    h("div", { style: s.tiny }, "判据"),
                    h(
                      "pre",
                      { style: Object.assign({}, s.mono, { whiteSpace: "pre-wrap", margin: "4px 0 0" }) },
                      task.rubric_excerpt,
                    ),
                  )
                : null,
              task.expected_behavior
                ? h(
                    "div",
                    null,
                    h("div", { style: s.tiny }, "期望行为"),
                    h(
                      "pre",
                      { style: Object.assign({}, s.mono, { whiteSpace: "pre-wrap", margin: "4px 0 0" }) },
                      task.expected_behavior,
                    ),
                  )
                : null,
              (task.judge_notes || []).length
                ? h(
                    "div",
                    null,
                    h("div", { style: s.tiny }, "判分备注"),
                    (task.judge_notes || []).map(function (note, index) {
                      return h(
                        "pre",
                        {
                          key: index,
                          style: Object.assign({}, s.mono, { whiteSpace: "pre-wrap", margin: "4px 0 0" }),
                        },
                        JSON.stringify(note, null, 1),
                      );
                    }),
                  )
                : null,
            ),
          )
        : null,
      h(
        Panel,
        {
          title: "轨迹时间线",
          hint: transcript
            ? "共 " + transcript.total_events + " 条 · 已读 " + (transcript.events || []).length +
              (transcript.damaged_events ? " · 损坏 " + transcript.damaged_events : "") +
              " · " + transcript.transcript_state
            : "读取中…",
          extra:
            transcript && transcript.next_cursor !== null
              ? h(Button, { size: "small", loading: loadingMore, onClick: more }, "再读 " + transcript.limit + " 条")
              : null,
        },
        transcript ? h(Timeline, { events: transcript.events }) : h(Spin, { size: "small" }),
      ),
    );
  }

  function ReportModule(props) {
    var s = useStyles();
    var jobId = props.jobId;
    var [detail, setDetail] = useState(null);
    var [error, setError] = useState(null);
    var [sensitivity, setSensitivity] = useState(props.defaultSensitivity || "shared");
    var [tab, setTab] = useState("overview");
    var [task, setTask] = useState(null);
    var [taskLoading, setTaskLoading] = useState("");
    var [taskQuery, setTaskQuery] = useState("");
    var [taskFilter, setTaskFilter] = useState("all");
    var [report, setReport] = useState(null);
    var [reportFormat, setReportFormat] = useState(props.defaultFormat || "md");
    var [reporting, setReporting] = useState(false);

    useEffect(
      function () {
        if (!jobId) return undefined;
        var alive = true;
        setDetail(null);
        setError(null);
        setTask(null);
        setReport(null);
        api
          .detail(jobId, sensitivity)
          .then(function (result) {
            if (alive) setDetail(result);
          })
          .catch(function (err) {
            if (alive) setError(errOf(err));
          });
        return function () {
          alive = false;
        };
      },
      [jobId, sensitivity],
    );

    function openTask(row) {
      setTaskLoading(row.task_id);
      api
        .taskDetail(jobId, row.task_id, sensitivity, row.attempt)
        .then(function (result) {
          setTask(result);
        })
        .catch(function (err) {
          message.error("单题详情读取失败：" + errOf(err).message);
        })
        .then(function () {
          setTaskLoading("");
        });
    }

    function makeReport() {
      setReporting(true);
      setReport(null);
      api
        .report(jobId, reportFormat, sensitivity)
        .then(setReport)
        .catch(function (err) {
          var info = errOf(err);
          message.error("报告生成失败：" + info.code + " " + info.message);
        })
        .then(function () {
          setReporting(false);
        });
    }

    function downloadReport() {
      var proxied = API + "/fetch?url=" + encodeURIComponent(report.url);
      var token = typeof host.getApiToken === "function" ? host.getApiToken() : "";
      fetch(host.getApiUrl(proxied), { headers: token ? { Authorization: "Bearer " + token } : {} })
        .then(function (response) {
          if (!response.ok) throw new Error("HTTP " + response.status);
          return response.blob();
        })
        .then(function (blob) {
          saveBlob(blob, report.filename);
        })
        .catch(function (err) {
          message.error("下载失败：" + err.message);
        });
    }

    var taskRows = useMemo(
      function () {
        if (!detail) return [];
        var needle = taskQuery.trim().toLowerCase();
        return (detail.tasks || []).filter(function (row) {
          if (taskFilter === "failed" && row.status !== "failed" && row.failure_reason !== "no_artifacts") {
            return false;
          }
          if (taskFilter === "low" && !(typeof row.score === "number" && row.score < 0.8)) return false;
          if (taskFilter === "unscored" && typeof row.score === "number") return false;
          if (!needle) return true;
          return [row.task_id, row.name, JSON.stringify(row.labels || {})]
            .join(" ")
            .toLowerCase()
            .indexOf(needle) >= 0;
        });
      },
      [detail, taskFilter, taskQuery],
    );

    if (error) {
      return h(
        "div",
        { style: s.stack },
        h(Button, { size: "small", onClick: props.onBack }, "← 返回评测列表"),
        h(Alert, { type: "error", showIcon: true, message: error.code, description: error.message }),
      );
    }
    if (!detail) {
      return h(
        "div",
        { style: Object.assign({}, s.card, { padding: 48, textAlign: "center" }) },
        h(Spin, null),
        h("div", { style: Object.assign({}, s.tiny, { marginTop: 8 }) }, "读取 " + jobId),
      );
    }

    var progress = detail.progress || { total: 0, by_status: {}, scored: 0 };
    var byStatus = progress.by_status || {};
    var score = detail.score || {};
    // A job that is still queued has no task rows yet, so ``progress.total`` is
    // zero while the submission already knows how many tasks it will run.  The
    // report should say "0 / 24, waiting" rather than "0 / 0", which reads as an
    // empty run.
    var planned = (detail.sources || []).reduce(function (sum, source) {
      return sum + (Number(source.task_count) || 0);
    }, 0);
    if (!progress.total && planned) {
      progress = Object.assign({}, progress, { total: planned });
    }

    var header = h(
      Panel,
      { pad: false },
      h(
        "div",
        { style: { padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 } },
        h(
          "div",
          { style: Object.assign({}, s.row, { justifyContent: "space-between", alignItems: "flex-start", paddingRight: 72 }) },
          h(
            "div",
            { style: Object.assign({}, s.row, { gap: 10, minWidth: 0 }) },
            h(Button, { size: "small", onClick: props.onBack }, "← 评测列表"),
            h(
              "div",
              { style: { display: "flex", flexDirection: "column", minWidth: 0 } },
              h(
                "div",
                { style: Object.assign({}, s.row, { gap: 8 }) },
                h("span", { style: { fontSize: 17, fontWeight: 600 } }, detail.purpose || "（未写目的）"),
                h(StatusPill, { text: statusMeta(detail.status).text, color: statusMeta(detail.status).color }),
              ),
              h(
                "div",
                { style: Object.assign({}, s.row, { gap: 8, marginTop: 2 }) },
                h(CopyId, { value: detail.job_id, full: true, label: "job id 已复制" }),
                h("span", { style: s.tiny }, detail.product || "—"),
                h("span", { style: s.tiny }, detail.submitter || "—"),
              ),
            ),
          ),
        ),
        h(
          "div",
          {
            style: {
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
              gap: 0,
              marginLeft: -14,
            },
          },
          h(ReportMetric, {
            label: "总分",
            value: h(ScoreText, { value: score.mean, bold: true }),
            hint: "计分 " + (progress.scored || 0) + " / " + progress.total + " 题",
          }),
          h(ReportMetric, {
            label: "完成",
            value: (byStatus.finished || 0) + " / " + progress.total,
            bar: h(MiniBar, {
              percent: progress.total ? (byStatus.finished || 0) / progress.total : 0,
              color: byStatus.failed ? s.token.colorError : s.token.colorPrimary,
            }),
          }),
          h(ReportMetric, {
            label: "分数区间",
            value:
              score.best === null || score.best === undefined
                ? "—"
                : fmtNum(score.best, 2) + " – " + fmtNum(score.worst, 2),
            hint: "最高 / 最低",
          }),
          h(ReportMetric, {
            label: "耗时",
            value: fmtDuration(
              detail.started_at && detail.finished_at
                ? (asDate(detail.finished_at) - asDate(detail.started_at)) / 1000
                : 0,
            ),
            hint: detail.finished_at ? fmtShort(detail.finished_at) + " 结束" : "未结束",
          }),
        ),
      ),
    );

    var statusLine = Object.keys(byStatus).sort().map(function (key) {
      var meta = statusMeta(key);
      return h(StatusPill, { key: key, text: meta.text + " " + byStatus[key], color: meta.color });
    });

    var overview = h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 14 } },
      h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "minmax(220px, 260px) 1fr", gap: 14 } },
        h(
          Panel,
          { title: "总分" },
          h(ScoreDial, {
            score: score.mean,
            caption: "计分 " + (score.count || 0) + " 题 · 共 " + progress.total + " 题",
          }),
          h("div", { style: Object.assign({}, s.row, { justifyContent: "center", marginTop: 8 }) }, statusLine),
        ),
        h(
          Panel,
          { title: "切片", hint: "按题目标签聚合平均分" },
          h(
            "div",
            { style: { display: "flex", flexDirection: "column", gap: 16, maxWidth: 520 } },
            h("div", null, h("div", { style: s.tiny }, "场景"),
              h(SliceBars, { data: detail.slices && detail.slices.scenario })),
            h("div", null, h("div", { style: s.tiny }, "能力"),
              h(SliceBars, { data: detail.slices && detail.slices.capability })),
          ),
        ),
      ),
      h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 14, alignItems: "start" } },
        h(
          Panel,
          { title: "配置" },
          h(
            "div",
            { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))", gap: 12 } },
            h("div", { style: { gridColumn: "1 / -1" } },
              h(Fact, { label: "ACP 地址" }, h("code", { style: s.mono }, detail.acp_url || "—"))),
            h(Fact, { label: "窗口" },
              detail.window
                ? windowLabel(detail.window.kind) + " · " + fmtShort(detail.window.not_before)
                : "—"),
            h(Fact, { label: "提交" }, fmtFull(detail.created_at)),
            h(Fact, { label: "开始" }, fmtFull(detail.started_at)),
          ),
          detail.error
            ? h(Alert, { type: "error", showIcon: true, style: { marginTop: 12 }, message: detail.error })
            : null,
        ),
        h(
          Panel,
          { title: "数据来源" },
          (detail.sources || []).length
            ? (detail.sources || []).map(function (source) {
                return h(
                  "div",
                  { key: source.dataset_id, style: Object.assign({}, s.row, { justifyContent: "space-between" }) },
                  h(
                    "div",
                    { style: s.row },
                    h(Tag, { bordered: false }, source.dataset_kind),
                    h("code", { style: s.mono }, source.dataset_id),
                  ),
                  h("span", { style: s.tiny }, source.task_count + " 题"),
                );
              })
            : h("span", { style: s.tiny }, "没有来源记录"),
        ),
      ),
      detail.env_fingerprint
        ? h(
            Panel,
            { title: "环境指纹", hint: "提交时自报，原样保留" },
            h(
              "pre",
              {
                style: Object.assign({}, s.mono, {
                  margin: 0,
                  whiteSpace: "pre-wrap",
                  background: s.token.colorFillQuaternary,
                  border: "1px solid " + s.token.colorBorder,
                  padding: 10,
                  borderRadius: s.token.borderRadius,
                }),
              },
              JSON.stringify(detail.env_fingerprint, null, 2),
            ),
          )
        : null,
    );

    var taskColumns = [
      {
        title: "题目",
        dataIndex: "name",
        render: function (_, row) {
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column", gap: 2, minWidth: 0 } },
            h("span", { style: { fontWeight: 600 } }, row.name || row.task_id),
            h("code", { style: Object.assign({}, s.mono, s.tiny) }, row.task_id),
          );
        },
      },
      {
        title: "标签",
        dataIndex: "labels",
        width: 190,
        render: function (value) {
          var parts = labelParts(value);
          return parts.length
            ? h(Space, { size: 2, wrap: true }, parts.map(function (part) {
                return h(Tag, { key: part, bordered: false }, part);
              }))
            : h("span", { style: s.tiny }, "—");
        },
      },
      {
        title: "状态",
        dataIndex: "status",
        width: 96,
        render: function (value, row) {
          return h(StatusPill, {
            taskStatus: value,
            text: statusMeta(value).text,
            title: row.failure_reason || "",
          });
        },
      },
      {
        title: "分数",
        dataIndex: "score",
        width: 78,
        render: function (value) {
          return h(ScoreText, { value: value, bold: true });
        },
      },
      {
        title: "耗时",
        dataIndex: "duration_s",
        width: 76,
        render: function (value) {
          return h("span", { style: Object.assign({}, s.mono, s.num) }, fmtDuration(value));
        },
      },
      {
        title: "trace_id",
        dataIndex: "trace_id",
        width: 140,
        render: function (value) {
          return value
            ? h("code", { style: s.mono }, String(value).slice(0, 12))
            : h("span", { style: s.tiny }, "—");
        },
      },
      {
        title: "",
        width: 66,
        render: function (_, row) {
          return h(
            Button,
            {
              size: "small",
              type: "link",
              loading: taskLoading === row.task_id,
              onClick: function (event) {
                event.stopPropagation();
                openTask(row);
              },
            },
            "查看",
          );
        },
      },
    ];

    var tasksTab = task
      ? h(TaskPanel, {
          jobId: jobId,
          task: task,
          sensitivity: sensitivity,
          onBack: function () {
            setTask(null);
          },
        })
      : h(
          "div",
          { style: { display: "flex", flexDirection: "column", gap: 12 } },
          h(
            "div",
            { style: s.row },
            h(Segmented, {
              size: "small",
              value: taskFilter,
              onChange: setTaskFilter,
              options: [
                { value: "all", label: "全部 " + (detail.tasks || []).length },
                { value: "failed", label: "异常" },
                { value: "low", label: "低分" },
                { value: "unscored", label: "未计分" },
              ],
            }),
            h(Input, {
              allowClear: true,
              size: "small",
              placeholder: "搜题名、task id、标签",
              style: { width: 240 },
              value: taskQuery,
              onChange: function (event) {
                setTaskQuery(event.target.value);
              },
            }),
            h("span", { style: s.tiny }, "点一行看题干、判分与轨迹"),
          ),
          h(Table, {
            size: "middle",
            rowKey: "task_id",
            dataSource: taskRows,
            columns: taskColumns,
            pagination: taskRows.length > 20 ? { pageSize: 20, size: "small" } : false,
            scroll: { x: 860 },
            onHeaderRow: function () {
              return { style: { background: s.token.colorFillQuaternary } };
            },
            onRow: function (row) {
              return {
                onClick: function () {
                  openTask(row);
                },
                style: { cursor: "pointer" },
              };
            },
            locale: {
              emptyText: h(EmptyState, {
                glyph: "◇",
                title: "没有符合条件的题目",
                hint: "换个筛选条件，或者清空搜索词。",
              }),
            },
          }),
        );

    var exportTab = h(
      "div",
      { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 14 } },
      h(
        Panel,
        { title: "生成报告文件", hint: "题干、trace_id 与 session_id 都在报告里" },
        h(
          "div",
          { style: s.row },
          h(Select, {
            size: "small",
            style: { width: 190 },
            value: reportFormat,
            onChange: setReportFormat,
            options: REPORT_FORMATS.map(function (format) {
              var disabled = format === "zip" && sensitivity !== "full";
              return {
                value: format,
                label: disabled ? format + "（仅完整版）" : format,
                disabled: disabled,
              };
            }),
          }),
          h(Button, { size: "small", type: "primary", loading: reporting, onClick: makeReport }, "生成"),
          report
            ? h(Button, { size: "small", onClick: downloadReport }, "下载 " + report.filename)
            : null,
        ),
        report
          ? h(
              "div",
              { style: Object.assign({}, s.stack, { marginTop: 12, gap: 4 }) },
              h("span", { style: s.tiny }, (report.size / 1024).toFixed(1) + " KB · sha256 " + report.sha256),
              h("span", { style: s.tiny }, "链接 " + untilText(report.expires_at) + "过期"),
            )
          : h("div", { style: Object.assign({}, s.tiny, { marginTop: 12 }) },
              "报告是一次性产物：每次生成都会写一份新文件，旧的按服务配置过期。"),
      ),
      h(
        Panel,
        { title: "报告里有什么" },
        h(
          "ul",
          { style: Object.assign({}, s.muted, { paddingLeft: 18, margin: 0, lineHeight: 1.9 }) },
          h("li", null, "总分、切片、逐题状态与分数"),
          h("li", null, "每题题干原文（截断到 1200 字符）"),
          h("li", null, "每题的 trace_id 与 session_id，可直接拿去搜日志"),
          h("li", null, "产物清单与大小" + (sensitivity === "full" ? "，可下载" : "（完整版可下载）")),
        ),
      ),
    );

    return h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 14 } },
      header,
      sensitivity === "full"
        ? h(Alert, {
            type: "warning",
            showIcon: true,
            message: "正在看完整版：含评分依据与他人产物，对外分享请切回 shared",
          })
        : null,
      h(Tabs, {
        activeKey: tab,
        onChange: setTab,
        tabBarExtraContent: h(
          Space,
          null,
          h(Space, { size: 6 },
            h("span", { style: s.tiny }, "档位"),
            h(Tooltip, { title: "完整版含评分依据与产物下载；对外分享用 shared" },
              h(Segmented, {
                size: "small",
                value: sensitivity,
                onChange: function (value) {
                  setSensitivity(value);
                  setTask(null);
                  // zip is only issued for the full tier, so carrying the choice
                  // back into shared would make the next 生成 a guaranteed 400.
                  if (value === "shared" && reportFormat === "zip") setReportFormat("md");
                },
                options: [
                  { value: "shared", label: "shared" },
                  { value: "full", label: "完整版" },
                ],
              }))),
          h(Button, {
            size: "small",
            onClick: function () {
              copyText(
                window.location.origin + window.location.pathname + "?app=pawbench-eval&job=" + jobId,
                "报告链接已复制",
              );
            },
          }, "复制链接"),
        ),
        items: [
          { key: "overview", label: "总览", children: overview },
          { key: "tasks", label: "题目（" + (detail.tasks || []).length + "）", children: tasksTab },
          { key: "export", label: "导出", children: exportTab },
        ],
      }),
    );
  }

  function labelParts(labels) {
    if (!labels) return [];
    var parts = [];
    ["scenario", "complexity", "environment"].forEach(function (key) {
      if (labels[key]) parts.push(labels[key]);
    });
    if (labels.modality) {
      parts.push(typeof labels.modality === "string" ? labels.modality : labels.modality.type);
    }
    if ((labels.capabilities || []).length) parts.push(labels.capabilities.join("/"));
    return parts.filter(Boolean);
  }

  // ── module: datasets ────────────────────────────────────────────────────

  function DatasetsModule(props) {
    var s = useStyles();
    var [editing, setEditing] = useState(null); // "view" | "upload" | "category" | null
    var [form, setForm] = useState({});
    var [busy, setBusy] = useState(false);
    var catalog = props.catalog || { datasets: [], categories: [] };

    function startView() {
      setForm({ id: "", name: "", description: "", categories: [], filter: {} });
      setEditing("view");
    }

    function startUpload() {
      setForm({ id: "", name: "", description: "", categories: [], file: null });
      setEditing("upload");
    }

    function submitView() {
      var filter = {};
      Object.keys(form.filter || {}).forEach(function (key) {
        var value = form.filter[key];
        if (value && value.length) filter[key] = value;
      });
      if (!Object.keys(filter).length) {
        message.warning("至少要给过滤器一个条件，空过滤器等于整份语料");
        return;
      }
      setBusy(true);
      api
        .createDataset({
          id: form.id,
          name: form.name,
          description: form.description,
          categories: form.categories,
          filter: filter,
        })
        .then(function () {
          message.success("数据集已创建");
          setEditing(null);
          return props.onRefresh();
        })
        .catch(function (err) {
          message.error("创建失败：" + errOf(err).message);
        })
        .then(function () {
          setBusy(false);
        });
    }

    function submitUpload() {
      if (!form.file) {
        message.warning("先选一个 zip 包");
        return;
      }
      var query =
        "id=" + encodeURIComponent(form.id) +
        "&name=" + encodeURIComponent(form.name) +
        "&description=" + encodeURIComponent(form.description || "");
      (form.categories || []).forEach(function (name) {
        query += "&categories=" + encodeURIComponent(name);
      });
      setBusy(true);
      uploadPackage(form.file, query)
        .then(function () {
          message.success("已上传");
          setEditing(null);
          return props.onRefresh();
        })
        .catch(function (err) {
          message.error("上传失败：" + errOf(err).message);
        })
        .then(function () {
          setBusy(false);
        });
    }

    function removeDataset(row) {
      api
        .deleteDataset(row.id)
        .then(function () {
          message.success("已删除");
          return props.onRefresh();
        })
        .catch(function (err) {
          message.error("删除失败：" + errOf(err).message);
        });
    }

    function removeCategory(row) {
      api
        .deleteCategory(row.name)
        .then(function () {
          message.success("分类已删除");
          return props.onRefresh();
        })
        .catch(function (err) {
          message.error("删除失败：" + errOf(err).message);
        });
    }

    var taskTotal = (catalog.datasets || []).reduce(function (sum, row) {
      return sum + (Number(row.task_count) || 0);
    }, 0);

    var columns = [
      {
        title: "数据集",
        dataIndex: "id",
        render: function (_, row) {
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column", gap: 2 } },
            h("span", { style: { fontWeight: 600 } }, row.name || row.id),
            h(
              "div",
              { style: Object.assign({}, s.row, { gap: 6 }) },
              h("code", { style: s.mono }, row.id),
              h(Tag, { bordered: false }, row.kind),
            ),
            row.description ? h("span", { style: s.tiny }, row.description) : null,
          );
        },
      },
      {
        title: "题数",
        dataIndex: "task_count",
        width: 72,
        render: function (value) {
          return h("span", { style: Object.assign({}, s.num, { fontWeight: 600 }) }, value);
        },
      },
      {
        title: "分类",
        dataIndex: "categories",
        width: 210,
        render: function (value) {
          if (!value || !value.length) return h("span", { style: s.tiny }, "未分类");
          return h(
            Space,
            { size: 2, wrap: true },
            value.map(function (name) {
              return h(Tag, { key: name, bordered: false }, name);
            }),
          );
        },
      },
      { title: "维护人", dataIndex: "owner", width: 100 },
      {
        title: "更新",
        dataIndex: "updated_at",
        width: 118,
        render: function (value) {
          return h("span", { style: s.tiny }, fmtShort(value));
        },
      },
      {
        title: "",
        width: 66,
        render: function (_, row) {
          var mine = !props.subject || row.owner === props.subject;
          var node = h(Button, { size: "small", type: "link", danger: true, disabled: !mine }, "删除");
          if (mine) {
            return h(
              Popconfirm,
              {
                title: "删除 " + row.id + "？",
                description: "跑过任务的删不掉，服务会拒绝。",
                okText: "删除",
                cancelText: "算了",
                onConfirm: function () {
                  removeDataset(row);
                },
              },
              node,
            );
          }
          return h(Tooltip, { title: "由 " + row.owner + " 维护" }, node);
        },
      },
    ];

    var categoryColumns = [
      { title: "分类", dataIndex: "name" },
      { title: "数据集数", dataIndex: "dataset_count", width: 96 },
      { title: "创建者", dataIndex: "created_by", width: 110 },
      {
        title: "",
        width: 66,
        render: function (_, row) {
          var mine = !props.subject || row.created_by === props.subject;
          var node = h(Button, { size: "small", type: "link", danger: true, disabled: !mine }, "删除");
          if (mine) {
            return h(
              Popconfirm,
              {
                title: "删除分类 " + row.name + "？",
                description: "只删空分类，还有数据集挂着会被拒。",
                okText: "删除",
                cancelText: "算了",
                onConfirm: function () {
                  removeCategory(row);
                },
              },
              node,
            );
          }
          return h(Tooltip, { title: "由 " + row.created_by + " 维护" }, node);
        },
      },
    ];

    function filterEditor() {
      var distribution = catalog.label_distribution || {};
      return h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: 10 } },
        FILTER_KEYS.map(function (key) {
          var values = Object.keys(distribution[key] || {});
          if (!values.length) {
            return h(
              Field,
              { key: key, label: key, hint: "手填值" },
              h(Select, {
                mode: "tags",
                style: { width: "100%" },
                value: (form.filter && form.filter[key]) || [],
                onChange: function (next) {
                  setForm(function (previous) {
                    var filter = Object.assign({}, previous.filter);
                    filter[key] = next;
                    return Object.assign({}, previous, { filter: filter });
                  });
                },
              }),
            );
          }
          return h(
            Field,
            { key: key, label: key },
            h(Select, {
              mode: "multiple",
              style: { width: "100%" },
              value: (form.filter && form.filter[key]) || [],
              options: values.map(function (value) {
                return { value: value, label: value + " · " + distribution[key][value] };
              }),
              onChange: function (next) {
                setForm(function (previous) {
                  var filter = Object.assign({}, previous.filter);
                  filter[key] = next;
                  return Object.assign({}, previous, { filter: filter });
                });
              },
            }),
          );
        }),
      );
    }

    var categoryOptions = (catalog.categories || []).map(function (entry) {
      return { value: entry.name, label: entry.name };
    });

    return h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 16 } },
      h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 12 } },
        h(StatCard, { label: "数据集", value: (catalog.datasets || []).length, hint: "视图 + 自定义包" }),
        h(StatCard, { label: "题目", value: taskTotal, hint: "各集合计" }),
        h(StatCard, { label: "分类", value: (catalog.categories || []).length, hint: "用于整组选题" }),
      ),
      h(
        Panel,
        {
          pad: false,
          children: h(
            "div",
            null,
            h(
              "div",
              { style: Object.assign({}, s.sectionHead, { padding: "14px 16px", marginBottom: 0 }) },
              h("div", { style: s.h2 }, "全部数据集"),
              h(
                Space,
                null,
                h(Button, { size: "small", onClick: startView }, "新建视图"),
                h(Button, { size: "small", onClick: startUpload }, "上传自定义集"),
                h(
                  Button,
                  {
                    size: "small",
                    onClick: function () {
                      setForm({ name: "", description: "" });
                      setEditing("category");
                    },
                  },
                  "分类管理",
                ),
              ),
            ),
            h(Table, {
              size: "middle",
              rowKey: "id",
              dataSource: catalog.datasets || [],
              columns: columns,
              pagination: (catalog.datasets || []).length > 15 ? { pageSize: 15, size: "small" } : false,
              scroll: { x: 820 },
              locale: {
                emptyText: h(EmptyState, {
                  glyph: "▤",
                  title: "还没有数据集",
                  hint: "「新建视图」从内置语料里切一片，「上传自定义集」提交一个 zip 任务包。",
                }),
              },
            }),
          ),
        },
      ),
      h(
        Modal,
        {
          open: editing === "view",
          title: "新建视图（从内置语料切一片）",
          onCancel: function () {
            setEditing(null);
          },
          onOk: submitView,
          confirmLoading: busy,
          okText: "创建",
          width: 660,
        },
        h(
          "div",
          { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 } },
          h(
            Field,
            { label: "id", hint: "字母或数字开头" },
            h(Input, {
              value: form.id || "",
              onChange: function (event) {
                setForm(Object.assign({}, form, { id: event.target.value }));
              },
            }),
          ),
          h(
            Field,
            { label: "显示名" },
            h(Input, {
              value: form.name || "",
              onChange: function (event) {
                setForm(Object.assign({}, form, { name: event.target.value }));
              },
            }),
          ),
        ),
        h(
          Field,
          { label: "说明" },
          h(Input.TextArea, {
            rows: 2,
            value: form.description || "",
            onChange: function (event) {
              setForm(Object.assign({}, form, { description: event.target.value }));
            },
          }),
        ),
        h(
          Field,
          { label: "归档分类" },
          h(Select, {
            mode: "multiple",
            style: { width: "100%" },
            value: form.categories || [],
            options: categoryOptions,
            onChange: function (next) {
              setForm(Object.assign({}, form, { categories: next }));
            },
          }),
        ),
        h("div", { style: Object.assign({}, s.muted, { marginBottom: 6 }) }, "过滤条件（至少一条）"),
        filterEditor(),
      ),
      h(
        Modal,
        {
          open: editing === "upload",
          title: "上传自定义任务包",
          onCancel: function () {
            setEditing(null);
          },
          onOk: submitUpload,
          confirmLoading: busy,
          okText: "上传",
          width: 660,
        },
        h(
          "div",
          { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 } },
          h(
            Field,
            { label: "id", hint: "字母或数字开头" },
            h(Input, {
              value: form.id || "",
              onChange: function (event) {
                setForm(Object.assign({}, form, { id: event.target.value }));
              },
            }),
          ),
          h(
            Field,
            { label: "显示名" },
            h(Input, {
              value: form.name || "",
              onChange: function (event) {
                setForm(Object.assign({}, form, { name: event.target.value }));
              },
            }),
          ),
        ),
        h(
          Field,
          { label: "说明" },
          h(Input.TextArea, {
            rows: 2,
            value: form.description || "",
            onChange: function (event) {
              setForm(Object.assign({}, form, { description: event.target.value }));
            },
          }),
        ),
        h(
          Field,
          { label: "归档分类" },
          h(Select, {
            mode: "multiple",
            style: { width: "100%" },
            value: form.categories || [],
            options: categoryOptions,
            onChange: function (next) {
              setForm(Object.assign({}, form, { categories: next }));
            },
          }),
        ),
        h(Upload, {
          beforeUpload: function (file) {
            setForm(Object.assign({}, form, { file: file }));
            return false;
          },
          maxCount: 1,
          accept: ".zip",
        }, h(Button, null, "选择 zip 包")),
      ),
      h(
        Modal,
        {
          open: editing === "category",
          title: "分类管理",
          onCancel: function () {
            setEditing(null);
          },
          footer: null,
          width: 640,
        },
        h(
          "div",
          { style: Object.assign({}, s.row, { marginBottom: 12 }) },
          h(Input, {
            placeholder: "新分类名",
            value: form.name || "",
            onChange: function (event) {
              setForm(Object.assign({}, form, { name: event.target.value }));
            },
            style: { width: 240 },
          }),
          h(
            Button,
            {
              type: "primary",
              onClick: function () {
                if (!form.name) return;
                api
                  .createCategory({ name: form.name, description: form.description || "" })
                  .then(function () {
                    message.success("分类已创建");
                    setForm(Object.assign({}, form, { name: "" }));
                    return props.onRefresh();
                  })
                  .catch(function (err) {
                    message.error("创建失败：" + errOf(err).message);
                  });
              },
            },
            "创建（同名幂等）",
          ),
        ),
        h(Table, {
          size: "small",
          rowKey: "name",
          dataSource: catalog.categories || [],
          columns: categoryColumns,
          pagination: false,
          locale: {
            emptyText: h(EmptyState, { glyph: "▤", title: "还没有分类", hint: "分类用于整组选题。" }),
          },
        }),
      ),
    );
  }

  // ── module: settings ────────────────────────────────────────────────────

  function SettingsModule(props) {
    var s = useStyles();
    var config = props.config || {};
    var [baseUrl, setBaseUrl] = useState(config.base_url || "");
    var [token, setToken] = useState("");
    var [subject, setSubject] = useState(config.subject || "");
    var [saving, setSaving] = useState(false);
    var [probe, setProbe] = useState(props.probe || null);
    var [error, setError] = useState(null);
    var [prefs, setPrefs] = useState({
      sensitivity: readLS("defaultSensitivity", "shared"),
      format: readLS("defaultFormat", "md"),
    });

    useEffect(
      function () {
        setBaseUrl(config.base_url || "");
        setSubject(config.subject || "");
      },
      [config.base_url, config.subject],
    );

    function save() {
      setSaving(true);
      setError(null);
      var body = { base_url: baseUrl, subject: subject };
      // An empty box means "keep the stored token" — the page never received it,
      // so sending "" would delete a working credential on every edit.
      if (token) body.token = token;
      api
        .saveConfig(body)
        .then(function () {
          setToken("");
          return api.probe();
        })
        .then(function (result) {
          setProbe(result);
          message.success("连接已保存");
          return props.onSaved();
        })
        .catch(function (err) {
          setError(errOf(err));
        })
        .then(function () {
          setSaving(false);
        });
    }

    function doProbe() {
      setSaving(true);
      api
        .probe()
        .then(setProbe)
        .catch(function (err) {
          setError(errOf(err));
        })
        .then(function () {
          setSaving(false);
        });
    }

    var reachable = probe && probe.reachable;
    return h(
      "div",
      { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))", gap: 16 } },
      h(
        Panel,
        { title: "服务连接", hint: "token 只留在本机插件目录，页面拿不到它" },
        error
          ? h(Alert, {
              type: "error",
              showIcon: true,
              style: { marginBottom: 12 },
              message: error.code,
              description: error.message,
            })
          : null,
        h(
          Field,
          { label: "评测服务地址", hint: "http:// 或 https:// 开头" },
          h(Input, {
            value: baseUrl,
            placeholder: "http://127.0.0.1:8471",
            onChange: function (event) {
              setBaseUrl(event.target.value);
            },
          }),
        ),
        h(
          Field,
          {
            label: "访问 token",
            hint: config.has_token ? "已保存 " + config.token_hint + "，留空则不变" : "白名单签发",
          },
          h(Input.Password, {
            value: token,
            placeholder: config.has_token ? "留空保持不变" : "粘贴 token",
            onChange: function (event) {
              setToken(event.target.value);
            },
          }),
        ),
        h(
          Field,
          { label: "我的身份", hint: "提交人名字，用于判断队列里哪一行是你的", last: true },
          h(Input, {
            value: subject,
            placeholder: "首次提交后自动识别",
            onChange: function (event) {
              setSubject(event.target.value);
            },
          }),
        ),
        h(
          "div",
          { style: Object.assign({}, s.row, { marginTop: 14 }) },
          h(Button, { type: "primary", loading: saving, onClick: save }, "保存并探测"),
          h(Button, { onClick: doProbe }, "只探测"),
        ),
      ),
      h(
        Panel,
        { title: "服务状态" },
        h(
          "div",
          { style: { display: "flex", flexDirection: "column", gap: 10 } },
          h(
            "div",
            { style: s.row },
            h(StatusPill, {
              text: reachable ? (probe.authorised === false ? "token 被拒" : "服务正常") : "连不上",
              color: reachable ? (probe.authorised === false ? "warning" : "success") : "error",
            }),
            h("span", { style: s.tiny },
              probe && probe.checked_at
                ? "检查于 " + String(probe.checked_at).replace("T", " ").slice(0, 16) + " UTC"
                : ""),
          ),
          h(Fact, { label: "地址" }, h("code", { style: s.mono }, config.base_url || "—")),
          h(Fact, { label: "服务标识" },
            (probe && probe.service && probe.service.public_base_url) || "—"),
          h(Fact, { label: "正在跑" },
            probe && probe.service ? (probe.service.active_attempts || 0) + " 个尝试" : "—"),
          h(Fact, { label: "当前身份" }, config.subject || "未知（提交一次后自动识别）"),
          h(Fact, { label: "配置来源" }, config.source === "file" ? "本机插件目录" : config.source === "env" ? "环境变量" : "未配置"),
        ),
      ),
      h(
        Panel,
        { title: "报告默认值", hint: "打开报告时的初始档位与导出格式" },
        h(
          "div",
          { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 } },
          h(
            Field,
            { label: "档位", last: true },
            h(Segmented, {
              value: prefs.sensitivity,
              onChange: function (value) {
                setPrefs(Object.assign({}, prefs, { sensitivity: value }));
                writeLS("defaultSensitivity", value);
              },
              options: [
                { value: "shared", label: "shared" },
                { value: "full", label: "完整版" },
              ],
            }),
          ),
          h(
            Field,
            { label: "导出格式", last: true },
            h(Select, {
              style: { width: "100%" },
              value: prefs.format,
              onChange: function (value) {
                setPrefs(Object.assign({}, prefs, { format: value }));
                writeLS("defaultFormat", value);
              },
              options: REPORT_FORMATS.map(function (format) {
                return { value: format, label: format };
              }),
            }),
          ),
        ),
      ),
      h(
        Panel,
        { title: "关于 token", style: { gridColumn: "1 / -1" } },
        h(
          Paragraph,
          { style: Object.assign({}, s.muted, { margin: 0, lineHeight: 1.8 }) },
          "页面调的是本插件的 /v1 代理，转发时才注入凭据：浏览器里没有 token，" +
            "插件目录里的配置文件是 0600。签发、吊销与 admin scope 都在服务的 auth 命令行里，" +
            "不在这个页面上——能改凭据的面板，等于把凭据交给了任何能打开它的人。",
        ),
      ),
    );
  }

  // ── page ────────────────────────────────────────────────────────────────

  function Dashboard() {
    var s = useStyles();
    var [view, setView] = useState("jobs");
    var [config, setConfig] = useState(null);
    var [probe, setProbe] = useState(null);
    var [probing, setProbing] = useState(false);
    var [catalog, setCatalog] = useState({ datasets: [], categories: [], label_distribution: {} });
    var [jobs, setJobs] = useState([]);
    var [loadError, setLoadError] = useState(null);
    var [newOpen, setNewOpen] = useState(false);
    var [reportJob, setReportJob] = useState(null);

    var refreshConfig = useCallback(function () {
      return api
        .config()
        .then(function (result) {
          setConfig(result);
          return result;
        })
        .catch(function (err) {
          setLoadError(errOf(err));
          return null;
        });
    }, []);

    var refreshCatalog = useCallback(function () {
      return Promise.all([api.datasets(), api.categories()])
        .then(function (results) {
          var datasets = results[0] || {};
          var categories = results[1] || {};
          setCatalog({
            datasets: datasets.datasets || [],
            label_distribution: datasets.label_distribution || {},
            categories: categories.categories || [],
          });
        })
        .catch(function (err) {
          var info = errOf(err);
          // An unconfigured service is not an error to shout about: the rail
          // already says so, and a red toast on every poll is noise.
          if (info.code !== "service_not_configured" && info.code !== "token_missing") {
            setLoadError(info);
          }
        });
    }, []);

    var refreshJobs = useCallback(function () {
      return api
        .jobs()
        .then(function (result) {
          setJobs((result && result.jobs) || []);
          setLoadError(null);
        })
        .catch(function (err) {
          var info = errOf(err);
          if (info.code !== "service_not_configured" && info.code !== "token_missing") {
            setLoadError(info);
          }
        });
    }, []);

    var runProbe = useCallback(function () {
      setProbing(true);
      return api
        .probe()
        .then(setProbe)
        .catch(function (err) {
          setProbe({ configured: true, reachable: false, reason: errOf(err).code });
        })
        .then(function () {
          setProbing(false);
        });
    }, []);

    useEffect(
      function () {
        refreshConfig();
        runProbe();
      },
      [refreshConfig, runProbe],
    );

    var ready = config && config.base_url && config.has_token;
    useEffect(
      function () {
        if (!ready) return undefined;
        refreshCatalog();
        refreshJobs();
        var timer = setInterval(function () {
          if (document.visibilityState === "visible") refreshJobs();
        }, POLL_MS);
        return function () {
          clearInterval(timer);
        };
      },
      [ready, refreshCatalog, refreshJobs],
    );

    // A `?job=` in the URL opens that report: the "复制链接" button on a report
    // is only useful if the link lands somewhere.
    useEffect(
      function () {
        if (!ready) return;
        try {
          var params = new URLSearchParams(window.location.search);
          var job = params.get("job");
          if (job) {
            setReportJob(job);
            setView("jobs");
          }
        } catch (err) {
          /* older webviews have no URLSearchParams; the page still works */
        }
      },
      [ready],
    );

    function onIdentity(subject) {
      setConfig(function (previous) {
        return previous ? Object.assign({}, previous, { subject: subject }) : previous;
      });
    }

    function openReport(jobId) {
      setReportJob(jobId);
      setView("jobs");
      try {
        var url = new URL(window.location.href);
        url.searchParams.set("job", jobId);
        window.history.replaceState({}, "", url.toString());
      } catch (err) {
        /* the address bar is a convenience, not the source of truth */
      }
    }

    function closeReport() {
      setReportJob(null);
      try {
        var url = new URL(window.location.href);
        url.searchParams.delete("job");
        window.history.replaceState({}, "", url.toString());
      } catch (err) {
        /* same */
      }
    }

    var running = jobs.filter(function (job) {
      return job.status === "running";
    }).length;
    var waiting = jobs.filter(function (job) {
      return ORDERABLE[job.status];
    }).length;

    var connectionState = "unconfigured";
    if (probe && probe.configured) {
      if (!probe.reachable) connectionState = "down";
      else if (probe.authorised === false) connectionState = "denied";
      else connectionState = "ok";
    }
    var connectionText = {
      ok: "服务正常",
      down: "连不上",
      denied: "token 被拒",
      unconfigured: "未配置服务",
    }[connectionState];
    var connectionColor = {
      ok: s.token.colorSuccess,
      down: s.token.colorError,
      denied: s.token.colorWarning,
      unconfigured: s.token.colorTextTertiary,
    }[connectionState];

    var title = view === "datasets" ? "数据集" : view === "settings" ? "配置" : "评测";
    var subtitle = {
      jobs: "提交评测、看队列、读报告",
      datasets: "从内置语料切视图，或上传自定义任务包",
      settings: "服务地址、token 与报告默认值",
    }[view];

    // Inside a report the page has its own title block; a module heading above
    // it would repeat "评测" over a screen that is already one evaluation.
    var header = reportJob
      ? null
      : h(
      "div",
      { style: Object.assign({}, s.row, { justifyContent: "space-between", alignItems: "flex-end" }) },
      h(
        "div",
        null,
        h("h1", { style: s.h1 }, title),
        h("div", { style: Object.assign({}, s.muted, { marginTop: 2 }) }, subtitle),
      ),
      h(
        "div",
        { style: Object.assign({}, s.row, { paddingRight: 76 }) },
        view === "jobs" && !reportJob
          ? h(
              Button,
              {
                type: "primary",
                disabled: !ready,
                onClick: function () {
                  setNewOpen(true);
                },
              },
              "＋ 新建评测",
            )
          : null,
        view !== "jobs"
          ? h(
              Button,
              {
                onClick: function () {
                  refreshCatalog();
                  refreshJobs();
                },
              },
              "刷新",
            )
          : null,
      ),
    );

    var body;
    if (view === "settings") {
      body = h(SettingsModule, {
        config: config || {},
        probe: probe,
        onSaved: function () {
          refreshConfig();
          refreshCatalog();
          refreshJobs();
          runProbe();
        },
      });
    } else if (view === "datasets") {
      body = h(DatasetsModule, {
        catalog: catalog,
        subject: config && config.subject,
        onRefresh: refreshCatalog,
      });
    } else if (reportJob) {
      body = h(ReportModule, {
        jobId: reportJob,
        onBack: closeReport,
        defaultSensitivity: readLS("defaultSensitivity", "shared"),
        defaultFormat: readLS("defaultFormat", "md"),
      });
    } else if (!ready) {
      body = h(
        Panel,
        { pad: false },
        h(EmptyState, {
          glyph: "🔌",
          title: "还没有连上评测服务",
          hint: "填一次服务地址和 token 就能用；token 只留在本机插件目录，页面拿不到它。",
          action: h(
            Button,
            {
              type: "primary",
              onClick: function () {
                setView("settings");
              },
            },
            "去配置",
          ),
        }),
      );
    } else {
      body = h(JobsModule, {
        jobs: jobs,
        subject: config && config.subject,
        onRefresh: refreshJobs,
        onOpen: openReport,
        onNew: function () {
          setNewOpen(true);
        },
      });
    }

    return h(
      "div",
      { style: s.page },
      h(
        "aside",
        { style: s.rail },
        h(
          "div",
          { style: Object.assign({}, s.row, { gap: 10, padding: "0 8px 18px" }) },
          h(
            "div",
            {
              style: {
                width: 30,
                height: 30,
                borderRadius: 8,
                background: s.token.colorPrimary,
                color: s.token.colorTextLightSolid,
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontSize: 15,
              },
            },
            "🧪",
          ),
          h(
            "div",
            null,
            h("div", { style: { fontSize: 13, fontWeight: 600, lineHeight: "18px" } }, "PawBench"),
            h("div", { style: s.tiny }, "远程评测"),
          ),
        ),
        h("div", { style: Object.assign({}, s.tiny, { padding: "0 8px 6px" }) }, "工作台"),
        h(
          "div",
          { style: { display: "flex", flexDirection: "column", gap: 2 } },
          h(NavItem, {
            glyph: "▦",
            label: "评测",
            badge: running ? String(running) : waiting ? String(waiting) : "",
            active: view === "jobs",
            onClick: function () {
              setView("jobs");
            },
          }),
          h(NavItem, {
            glyph: "▤",
            label: "数据集",
            badge: String((catalog.datasets || []).length),
            active: view === "datasets",
            onClick: function () {
              setView("datasets");
            },
          }),
          h(NavItem, {
            glyph: "⚙",
            label: "配置",
            active: view === "settings",
            onClick: function () {
              setView("settings");
            },
          }),
        ),
        h("div", { style: { flex: 1 } }),
        h(
          "div",
          {
            style: Object.assign({}, s.card, {
              padding: 10,
              background: s.token.colorFillQuaternary,
              cursor: "pointer",
            }),
            onClick: function () {
              runProbe();
            },
            title: "点一下重新探测",
          },
          h(
            "div",
            { style: Object.assign({}, s.row, { gap: 6 }) },
            h(Dot, { color: connectionColor }),
            h("span", { style: { fontSize: 12, fontWeight: 500 } }, connectionText),
            probing ? h(Spin, { size: "small" }) : null,
          ),
          h(
            "div",
            { style: Object.assign({}, s.tiny, { marginTop: 2, wordBreak: "break-all" }) },
            (config && config.base_url) || "还没有填写地址",
          ),
        ),
      ),
      h(
        "main",
        { style: s.main },
        header,
        loadError
          ? h(Alert, {
              type: "error",
              showIcon: true,
              closable: true,
              onClose: function () {
                setLoadError(null);
              },
              message: loadError.code,
              description: loadError.message,
            })
          : null,
        body,
      ),
      h(NewJobModal, {
        open: newOpen,
        catalog: catalog,
        onClose: function () {
          setNewOpen(false);
        },
        onIdentity: onIdentity,
        onSubmitted: function (result) {
          setNewOpen(false);
          refreshJobs();
          if (result && result.job_id) openReport(result.job_id);
        },
      }),
    );
  }

  // ── route registration ──────────────────────────────────────────────────

  Q.registerRoutes("pawbench-eval", [
    {
      path: "/apps/pawbench-eval",
      component: Dashboard,
      label: "PawBench 评测",
      icon: "🧪",
      priority: 60,
    },
  ]);
})();
