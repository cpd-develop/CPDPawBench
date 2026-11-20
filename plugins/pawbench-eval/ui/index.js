/**
 * PawBench Eval — dashboard (runtime-loaded plugin frontend).
 *
 * The host fetches this file, wraps it in a Blob and `import()`s it, so it is a
 * module with no relative imports and no bundler: React, antd and the icon set
 * come from `window.QwenPaw.host`. Everything the page draws is one page — the
 * design put submission, queue, results and datasets in sections on purpose
 * (design `§12`), not behind tabs, because the whole point is seeing what is
 * queued while writing the next submission.
 *
 * Colour never appears literally: every surface/text/border value comes from
 * `theme.useToken()`, which is the host's own theme, so light and dark are the
 * same code path and the design system's "no hardcoded colour" rule holds
 * without a second stylesheet.
 *
 * Three interaction decisions were made with the reviewer and are implemented
 * here as chosen: buttons for reordering (not drag), one inline submission form
 * (not a two-step wizard), and a modal for the three-level drill-down (not a
 * right-hand drawer).
 */
(function () {
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
  var useRef = React.useRef;

  var Button = antd.Button;
  var Card = antd.Card;
  var Table = antd.Table;
  var Tag = antd.Tag;
  var Space = antd.Space;
  var Select = antd.Select;
  var Input = antd.Input;
  var InputNumber = antd.InputNumber;
  var Modal = antd.Modal;
  var Descriptions = antd.Descriptions;
  var Tabs = antd.Tabs;
  var Collapse = antd.Collapse;
  var Segmented = antd.Segmented;
  var Alert = antd.Alert;
  var Tooltip = antd.Tooltip;
  var Empty = antd.Empty;
  var Spin = antd.Spin;
  var Popconfirm = antd.Popconfirm;
  var DatePicker = antd.DatePicker;
  var Upload = antd.Upload;
  var Typography = antd.Typography;
  var Divider = antd.Divider;
  var Progress = antd.Progress;
  var Badge = antd.Badge;
  var List = antd.List;
  var message = antd.message;
  var useToken = antd.theme.useToken;

  var Text = Typography.Text;
  var Paragraph = Typography.Paragraph;
  var Title = Typography.Title;

  // ── constants ───────────────────────────────────────────────────────────

  var API = "/pawbench-eval";
  var POLL_MS = 5000;
  var LS = "pawbench-eval.";
  var ALL_STATUSES = ["new", "queued", "scheduled", "running", "finished", "failed", "canceled"];
  //: Label cell of a definition list: 96px and never wrapped, so "判分方式" stays
  //: on one line instead of stacking two characters per row in a narrow column.
  var FACT_LABEL_STYLE = { width: 96, whiteSpace: "nowrap" };
  //: A flex column stretches its children; a button that should stay button-sized
  //: says so, otherwise "← 返回概览" spans the whole modal.
  var ALIGN_START = { alignSelf: "flex-start" };
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

  // ── small helpers ───────────────────────────────────────────────────────

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
    taskDetail: function (jobId, taskId, sensitivity) {
      return call(
        "GET",
        "/v1/jobs/" + encodeURIComponent(jobId) + "/tasks/" + encodeURIComponent(taskId) +
          "/detail?sensitivity=" + sensitivity,
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

  // ── shared bits ─────────────────────────────────────────────────────────

  function useStyles() {
    var token = useToken();
    return {
      token: token,
      muted: { color: token.colorTextSecondary, fontSize: 12 },
      tiny: { color: token.colorTextTertiary, fontSize: 12 },
      panel: {
        background: token.colorFillQuaternary,
        border: "1px solid " + token.colorBorderSecondary,
        borderRadius: token.borderRadiusLG,
        padding: 12,
      },
      card: { borderRadius: token.borderRadiusLG },
      mono: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12 },
      row: { display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" },
      stack: { display: "flex", flexDirection: "column", gap: 12 },
    };
  }

  function Field(props) {
    var s = useStyles();
    return h(
      "div",
      { style: { marginBottom: 12 } },
      h("div", { style: Object.assign({}, s.muted, { marginBottom: 4 }) }, props.label, props.hint
        ? h("span", { style: { marginLeft: 6, color: s.token.colorTextTertiary } }, props.hint)
        : null),
      props.children,
    );
  }

  function Dot(props) {
    var s = useStyles();
    return h("span", {
      style: {
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: "50%",
        background: props.color,
        marginRight: 6,
      },
    });
  }

  // ── connection ──────────────────────────────────────────────────────────

  function ConnectionBar(props) {
    var s = useStyles();
    var probe = props.probe;
    var state = "unconfigured";
    if (probe && probe.configured) {
      if (!probe.reachable) state = "down";
      else if (probe.authorised === false) state = "denied";
      else state = "ok";
    }
    var colors = {
      ok: s.token.colorSuccess,
      down: s.token.colorError,
      denied: s.token.colorWarning,
      unconfigured: s.token.colorTextTertiary,
    };
    var labels = {
      ok: "服务正常",
      down: "连不上",
      denied: "token 被拒",
      unconfigured: "未配置",
    };
    return h(
      "div",
      { style: Object.assign({}, s.row, { justifyContent: "space-between" }) },
      h(
        "div",
        { style: s.row },
        h("span", null, h(Dot, { color: colors[state] }), labels[state]),
        props.config && props.config.base_url
          ? h(Text, { style: s.mono, copyable: false }, props.config.base_url)
          : null,
        props.config && props.config.has_token
          ? h(Tag, { bordered: false }, "token " + props.config.token_hint)
          : h(Tag, { color: "warning", bordered: false }, "无 token"),
        props.config && props.config.subject
          ? h(Tag, { bordered: false }, "身份 " + props.config.subject)
          : h(Tooltip, { title: "首次提交后自动识别；也可以服务连接里手填，用于判断哪一行是你的" },
              h(Tag, { bordered: false, style: s.tiny }, "身份未知")),
      ),
      h(
        "div",
        { style: s.row },
        h(
          Button,
          { size: "small", onClick: props.onProbe, loading: props.probing },
          "重新探测",
        ),
        h(Button, { size: "small", type: "primary", ghost: true, onClick: props.onEdit }, "服务连接"),
      ),
    );
  }

  function ConnectionModal(props) {
    var [baseUrl, setBaseUrl] = React.useState("");
    var [token, setToken] = React.useState("");
    var [subject, setSubject] = React.useState("");
    var [saving, setSaving] = React.useState(false);
    var [probe, setProbe] = React.useState(null);
    var [error, setError] = React.useState(null);

    useEffect(
      function () {
        if (!props.open) return;
        var config = props.config || {};
        setBaseUrl(config.base_url || "");
        setSubject(config.subject || "");
        setToken("");
        setError(null);
        setProbe(props.probe || null);
      },
      [props.open, props.config],
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

    var s = useStyles();
    return h(
      Modal,
      {
        open: props.open,
        title: "服务连接",
        onCancel: props.onClose,
        footer: [
          h(
            Button,
            {
              key: "probe",
              onClick: function () {
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
              },
            },
            "探测",
          ),
          h(Button, { key: "save", type: "primary", loading: saving, onClick: save }, "保存"),
        ],
        width: 560,
      },
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
          hint: props.config && props.config.has_token
            ? "已保存 " + props.config.token_hint + "，留空则不变"
            : "白名单签发的一次性 token",
        },
        h(Input.Password, {
          value: token,
          placeholder: props.config && props.config.has_token ? "留空保持不变" : "粘贴 token",
          onChange: function (event) {
            setToken(event.target.value);
          },
        }),
      ),
      h(
        Field,
        { label: "我的身份", hint: "提交人名字，用于判断队列里哪一行是你的" },
        h(Input, {
          value: subject,
          placeholder: "首次提交后自动识别",
          onChange: function (event) {
            setSubject(event.target.value);
          },
        }),
      ),
      probe
        ? h(
            "div",
            { style: s.panel },
            probe.reachable
              ? h(Text, null,
                  "服务可达" +
                    (probe.service && probe.service.public_base_url
                      ? "：" + probe.service.public_base_url
                      : "") +
                    "；正在跑 " + ((probe.service && probe.service.active_attempts) || 0) + " 个任务" +
                    (probe.authorised === false ? "；但 token 被拒（401/403）" : ""))
              : h(Text, { type: "danger" }, "连不上：" + (probe.reason || "未知原因")),
          )
        : null,
      h(
        Paragraph,
        { style: Object.assign({}, s.tiny, { marginTop: 12, marginBottom: 0 }) },
        "token 只保存在本机插件目录里，前端永远拿不到它：页面调的是本插件的 /v1 代理，" +
          "转发时才注入凭据。",
      ),
    );
  }

  // ── dataset picker + resolve ────────────────────────────────────────────

  function SelectorPanel(props) {
    var s = useStyles();
    var resolved = props.resolved;
    if (props.loading) {
      return h("div", { style: s.panel }, h(Spin, { size: "small" }), " 正在解析选择…");
    }
    if (props.error) {
      return h(Alert, {
        type: "error",
        showIcon: true,
        message: "选择无法解析",
        description: props.error.code + "：" + props.error.message,
      });
    }
    if (!resolved) {
      return h("div", { style: Object.assign({}, s.panel, s.tiny) }, "选定分类或数据集后，这里显示将跑到哪些题。");
    }
    var datasets = Object.keys(resolved.by_dataset || {});
    var categories = Object.keys(resolved.categories_expanded || {});
    var unknown = resolved.unknown_ids || [];
    return h(
      "div",
      { style: s.panel },
      h(
        "div",
        { style: s.row },
        h(Text, { strong: true, style: { fontSize: 20 } }, resolved.task_count),
        h("span", { style: s.muted }, "道题"),
        resolved.duplicates_removed > 0
          ? h(Tag, { color: "gold" }, "去重 " + resolved.duplicates_removed + " 道")
          : null,
        h("span", { style: s.tiny }, "摘要 " + (resolved.task_ids_digest || "")),
      ),
      datasets.length
        ? h(
            "div",
            { style: Object.assign({}, s.row, { marginTop: 8 }) },
            h("span", { style: s.tiny }, "按来源："),
            datasets.map(function (name) {
              return h(Tag, { key: name, bordered: false }, name + " · " + resolved.by_dataset[name]);
            }),
          )
        : null,
      categories.length
        ? h(
            "div",
            { style: Object.assign({}, s.row, { marginTop: 8 }) },
            h("span", { style: s.tiny }, "分类展开："),
            categories.map(function (name) {
              var entry = resolved.categories_expanded[name] || {};
              var count = Array.isArray(entry) ? entry.length : entry.task_count;
              return h(Tag, { key: name, bordered: false }, name + " · " + (count || 0));
            }),
          )
        : null,
      unknown.length
        ? h(Alert, {
            style: { marginTop: 8 },
            type: "warning",
            showIcon: true,
            message: unknown.length + " 个 id 解析不出来",
            description: unknown.slice(0, 6).join("、") + (unknown.length > 6 ? " 等" : ""),
          })
        : null,
      (resolved.task_ids || []).length
        ? h(
            "details",
            { style: { marginTop: 8 } },
            h("summary", { style: Object.assign({}, s.tiny, { cursor: "pointer" }) }, "题目清单"),
            h(
              "div",
              { style: Object.assign({}, s.mono, { marginTop: 6, maxHeight: 160, overflow: "auto" }) },
              resolved.task_ids.join("\n"),
            ),
          )
        : null,
    );
  }

  // ── submission ──────────────────────────────────────────────────────────

  function SubmitSection(props) {
    var s = useStyles();
    var catalog = props.catalog;
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
      !submitting && acpUrl.trim() && (!selectorEmpty) && resolved && !resolving && !windowProblem;

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
          setReceipt(result);
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
          var info = errOf(err);
          setReceipt({ error: info });
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
      Card,
      { title: "提交评测", style: s.card, extra: h(Text, { style: s.tiny }, "单页填写，选完立刻显示题量") },
      h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 } },
        h(
          Field,
          { label: "ACP 地址", hint: "被评测端" },
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
          { label: "评测产品" },
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
          { label: "评测目的" },
          h(Input, {
            value: purpose,
            placeholder: "夜间冒烟 / 回归 / 发版前",
            onChange: function (event) {
              setPurpose(event.target.value);
            },
          }),
        ),
      ),
      h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 } },
        h(
          Field,
          { label: "分类（整组）", hint: "与下面单选混合生效" },
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
          { label: "数据集" },
          h(Select, {
            mode: "multiple",
            allowClear: true,
            style: { width: "100%" },
            placeholder: "挑具体的数据集，可与分类混选",
            value: datasetIds,
            options: datasetOptions,
            onChange: setDatasetIds,
          }),
        ),
      ),
      h(SelectorPanel, { resolved: resolved, loading: resolving, error: resolveError }),
      h(Divider, { style: { margin: "16px 0" } }),
      h(
        "div",
        { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 } },
        h(
          Field,
          { label: "可运行时间" },
          h(Segmented, {
            value: kind,
            onChange: setKind,
            options: [
              { value: "immediate", label: "即时" },
              { value: "night", label: "夜间" },
              { value: "custom", label: "自定义区间" },
            ],
          }),
        ),
        kind === "custom"
          ? h(
              Field,
              { label: "开始时间（本地）" },
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
              { label: "结束时间（本地）" },
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
            style: { marginBottom: 12 },
            message: "夜间窗口由服务的 schedule.night_window 决定，前端不带时间；提交后窗口区间会回填。",
          })
        : null,
      h(
        "div",
        { style: Object.assign({}, s.panel, { display: "flex", flexDirection: "column", gap: 4 }) },
        h("div", { style: s.row },
          h("span", { style: s.muted }, "本地时区"),
          h(Text, { style: s.mono }, localZone() + " " + offsetLabel(new Date()))),
        h("div", { style: s.row },
          h("span", { style: s.muted }, "服务时区"),
          h(Text, { style: s.mono }, serviceZone || "未知（提交后由服务回填）")),
        kind === "custom" && customStart
          ? h("div", { style: s.row },
              h("span", { style: s.muted }, "起跑"),
              h(Text, { style: s.mono }, fmtFull(customStart) + " 本地"),
              h(Text, { style: s.tiny }, "/ " + fmtUtc(customStart) + " UTC"),
              h(Text, { style: s.tiny }, untilText(customStart)))
          : null,
      ),
      windowProblem
        ? h(Alert, { type: "warning", showIcon: true, style: { marginTop: 12 }, message: windowProblem })
        : null,
      h(
        "div",
        { style: Object.assign({}, s.row, { marginTop: 16, justifyContent: "space-between" }) },
        h(
          "span",
          { style: s.tiny },
          "窗口容量（题数 × 平均耗时 ÷ 并发）由服务在提交时估算；超出会随提交结果返回，不阻止提交。",
        ),
        h(Button, { type: "primary", loading: submitting, disabled: !canSubmit, onClick: submit }, "提交排队"),
      ),
      receipt && receipt.error
        ? h(Alert, {
            style: { marginTop: 12 },
            type: "error",
            showIcon: true,
            message: "提交被拒：" + receipt.error.code,
            description: h(
              "div",
              null,
              h("div", null, receipt.error.message),
              receipt.error.details
                ? h("pre", { style: Object.assign({}, s.mono, { margin: "6px 0 0" }) },
                    JSON.stringify(receipt.error.details, null, 1))
                : null,
            ),
          })
        : null,
      receipt && !receipt.error
        ? h(
            "div",
            { style: { marginTop: 12 } },
            h(Alert, {
              type: receipt.warning ? "warning" : "success",
              showIcon: true,
              message: receipt.warning
                ? "已排队，但窗口可能装不下"
                : "已排队：" + receipt.job_id,
              description: receipt.warning
                ? "窗口 " + receipt.warning.window_seconds + " 秒，计划 " +
                  receipt.warning.tasks_planned + " 题，平均 " + receipt.warning.avg_task_seconds +
                  " 秒/题，预计只能完成约 " + receipt.warning.tasks_likely_completable + " 题"
                : "队列位置 " + fmtNum(receipt.queue_pos, 1) + "，前面还有 " + receipt.queue_ahead + " 个；" +
                  "窗口 " + windowLabel(receipt.window && receipt.window.kind) + " " +
                  fmtShort(receipt.window && receipt.window.not_before) +
                  (receipt.window && receipt.window.not_after
                    ? " → " + fmtShort(receipt.window.not_after)
                    : ""),
            }),
          )
        : null,
    );
  }

  // ── queue ───────────────────────────────────────────────────────────────

  function QueueSection(props) {
    var s = useStyles();
    var [filter, setFilter] = useState("waiting");
    var [busy, setBusy] = useState("");
    var jobs = props.jobs || [];

    var waiting = useMemo(
      function () {
        return jobs
          .filter(function (job) {
            return ORDERABLE[job.status];
          })
          .sort(function (a, b) {
            return a.queue_pos - b.queue_pos;
          });
      },
      [jobs],
    );
    var running = useMemo(
      function () {
        return jobs.filter(function (job) {
          return job.status === "running";
        });
      },
      [jobs],
    );

    var rows = useMemo(
      function () {
        if (filter === "waiting") return waiting;
        if (filter === "running") return running;
        return jobs.slice().sort(function (a, b) {
          return (b.created_at || "").localeCompare(a.created_at || "");
        });
      },
      [filter, waiting, running, jobs],
    );

    function move(job, direction) {
      var index = waiting.indexOf(job);
      var target = null;
      if (direction === "top") {
        var first = waiting[0];
        if (first && first.job_id !== job.job_id) target = { before_id: first.job_id };
      } else if (direction === "bottom") {
        var last = waiting[waiting.length - 1];
        if (last && last.job_id !== job.job_id) target = { after_id: last.job_id };
      } else if (direction === "up") {
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
          var info = errOf(err);
          message.error("调序被拒：" + info.message);
          // A refused move usually means the neighbour moved under us; the list
          // has to converge on the service's order, not stay where it was drawn.
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

    function disabledReason(job) {
      if (job.status === "running") return "运行中不能调序，只能取消";
      if (!ORDERABLE[job.status]) return "只有排队中的任务能调序";
      if (props.subject && job.submitter !== props.subject) {
        return "这行是 " + job.submitter + " 的，只能调自己的";
      }
      if (!props.subject) return "身份未知，点下去由服务判定；可在「服务连接」里手填身份";
      return "";
    }

    function orderButtons(job) {
      var index = waiting.indexOf(job);
      var reason = disabledReason(job);
      var blocked = Boolean(reason) || busy === job.job_id;
      var atTop = index === 0;
      var atBottom = index === waiting.length - 1;
      function button(key, label, glyph, direction, disabledExtra) {
        var disabled = blocked || disabledExtra;
        // The glyph is decoration: an arrow read aloud is "up arrow", not "上移
        // 一位", so the accessible name comes from `aria-label`. This is the
        // reason the reviewer picked buttons over dragging — a drag handle is
        // unreachable without a pointer.
        var node = h(
          Button,
          {
            size: "small",
            type: "text",
            key: key,
            "aria-label": label,
            disabled: disabled,
            onClick: function () {
              move(job, direction);
            },
          },
          glyph,
        );
        if (disabled) {
          return h(Tooltip, { key: key, title: disabledExtra ? "已经在" + label + "了" : reason }, node);
        }
        return h(Tooltip, { key: key, title: label }, node);
      }
      return h(
        Space,
        { size: 0 },
        button("top", "移到队首", "⇈", "top", atTop),
        button("up", "上移一位", "↑", "up", atTop),
        button("down", "下移一位", "↓", "down", atBottom),
        button("bottom", "移到队尾", "⇊", "bottom", atBottom),
      );
    }

    var columns = [
      {
        title: "状态",
        dataIndex: "status",
        width: 92,
        render: function (value) {
          var meta = statusMeta(value);
          return h(Tag, { color: meta.color }, meta.text);
        },
      },
      {
        title: "任务",
        dataIndex: "purpose",
        render: function (_, job) {
          var mine = props.subject && job.submitter === props.subject;
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column", gap: 2 } },
            h("div", { style: s.row },
              h(Text, { strong: true }, job.purpose || "（未写目的）"),
              mine ? h(Tag, { color: "blue", bordered: false }, "我的") : null),
            h("div", { style: s.row },
              h(Text, { style: s.mono }, shortId(job.job_id)),
              h(Text, { style: s.tiny }, job.product || ""),
              h(Text, { style: s.tiny }, job.acp_url || "")),
          );
        },
      },
      { title: "提交人", dataIndex: "submitter", width: 110 },
      {
        title: "窗口",
        dataIndex: "not_before",
        width: 190,
        render: function (_, job) {
          var waiting = job.status === "scheduled" || job.status === "queued";
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column" } },
            h(Text, { style: { fontSize: 12 } },
              windowLabel(job.window_kind) + " · " + fmtShort(job.not_before)),
            h(Text, { style: s.tiny },
              job.not_after ? "至 " + fmtShort(job.not_after) : "无截止"),
            waiting && job.window_kind !== "immediate"
              ? h(Text, { style: s.tiny }, untilText(job.not_before))
              : null,
          );
        },
      },
      {
        title: "位置",
        dataIndex: "queue_pos",
        width: 80,
        render: function (value) {
          return h(Text, { style: s.mono }, fmtNum(value, 1));
        },
      },
      {
        title: "操作",
        width: 250,
        render: function (_, job) {
          var canCancel = !TERMINAL[job.status];
          return h(
            Space,
            { size: 4 },
            orderButtons(job),
            canCancel
              ? h(
                  Popconfirm,
                  {
                    title: "取消这个任务？",
                    description: job.status === "running" ? "运行中的会话会被停掉，已跑完的题保留。" : "取消后不能恢复。",
                    okText: "取消任务",
                    cancelText: "算了",
                    onConfirm: function () {
                      cancel(job);
                    },
                  },
                  h(Button, { size: "small", danger: true, type: "text", loading: busy === job.job_id }, "取消"),
                )
              : null,
            h(
              Button,
              {
                size: "small",
                type: "link",
                onClick: function () {
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
      Card,
      {
        title: "队列",
        style: s.card,
        extra: h(Segmented, {
          size: "small",
          value: filter,
          onChange: setFilter,
          options: [
            { value: "waiting", label: "等待中 " + waiting.length },
            { value: "running", label: "运行中 " + running.length },
            { value: "all", label: "全部 " + jobs.length },
          ],
        }),
      },
      h(Table, {
        size: "small",
        rowKey: "job_id",
        dataSource: rows,
        columns: columns,
        pagination: rows.length > 20 ? { pageSize: 20, size: "small" } : false,
        scroll: { x: 980 },
        locale: {
          emptyText: h(Empty, {
            image: Empty.PRESENTED_IMAGE_SIMPLE,
            description: filter === "waiting" ? "队列是空的" : "没有任务",
          }),
        },
      }),
    );
  }

  // ── results ─────────────────────────────────────────────────────────────

  function SliceBars(props) {
    var s = useStyles();
    var entries = Object.keys(props.data || {});
    if (!entries.length) return h(Text, { style: s.tiny }, "暂无可用切片");
    return h(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 4 } },
      entries.map(function (name) {
        var value = props.data[name];
        return h(
          "div",
          { key: name, style: { display: "flex", alignItems: "center", gap: 8 } },
          h("span", { style: Object.assign({ width: 180 }, s.tiny), title: name }, name),
          h("div", { style: { flex: 1 } },
            h(Progress, {
              percent: Math.round((Number(value) || 0) * 100),
              size: "small",
              showInfo: false,
              strokeColor: s.token.colorPrimary,
            })),
          h(Text, { style: Object.assign({ width: 56, textAlign: "right" }, s.mono) }, fmtPct(value)),
        );
      }),
    );
  }

  function ResultsSection(props) {
    var s = useStyles();
    var finished = (props.jobs || []).filter(function (job) {
      return TERMINAL[job.status];
    });
    var [cache, setCache] = useState({});
    var [loading, setLoading] = useState("");

    function load(jobId) {
      if (cache[jobId] || loading === jobId) return;
      setLoading(jobId);
      api
        .results(jobId)
        .then(function (result) {
          setCache(function (previous) {
            var next = Object.assign({}, previous);
            next[jobId] = result;
            return next;
          });
        })
        .catch(function (err) {
          message.error("结果读取失败：" + errOf(err).message);
        })
        .then(function () {
          setLoading("");
        });
    }

    if (!finished.length) {
      return h(Card, { title: "结果", style: s.card },
        h(Empty, { image: Empty.PRESENTED_IMAGE_SIMPLE, description: "还没有跑完的任务" }));
    }

    return h(
      Card,
      { title: "结果", style: s.card },
      h(Collapse, {
        onChange: function (keys) {
          keys.forEach(load);
        },
        items: finished.map(function (job) {
          var result = cache[job.job_id];
          var meta = statusMeta(job.status);
          var flagged = [];
          if (result) {
            if (result.tasks_errored) flagged.push("出错 " + result.tasks_errored);
            if (result.tasks_missing) flagged.push("缺失 " + result.tasks_missing);
            if (result.missing_metadata) flagged.push("无元数据 " + result.missing_metadata);
          }
          return {
            key: job.job_id,
            label: h(
              "div",
              { style: Object.assign({}, s.row, { justifyContent: "space-between" }) },
              h("div", { style: s.row },
                h(Tag, { color: meta.color }, meta.text),
                h(Text, { strong: true }, job.purpose || "（未写目的）"),
                h(Text, { style: s.tiny }, shortId(job.job_id) + " · " + job.submitter),
                h(Text, { style: s.tiny }, fmtShort(job.finished_at || job.created_at))),
              h("div", { style: s.row },
                flagged.map(function (text) {
                  return h(Tag, { key: text, color: "error" }, text);
                }),
                result
                  ? h(Text, { style: s.mono }, "总分 " + fmtPct(result.overall))
                  : null),
            ),
            children: h(
              "div",
              { style: s.stack },
              loading === job.job_id || !result
                ? h(Spin, { size: "small" })
                : h(
                    "div",
                    { style: s.stack },
                    h("div", { style: s.row },
                      h(Text, { style: s.muted }, "总分"),
                      h(Text, { style: s.mono }, fmtPct(result.overall)),
                      h(Text, { style: s.muted }, "规则判分"),
                      h(Text, { style: s.mono }, fmtPct(result.automated)),
                      h(Text, { style: s.muted }, "LLM 判分"),
                      h(Text, { style: s.mono }, fmtPct(result.judge)),
                      h(Text, { style: s.muted }, "计分/总数"),
                      h(Text, { style: s.mono }, result.tasks + "/" + result.tasks_total)),
                    h(
                      "div",
                      { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 } },
                      h("div", null, h("div", { style: s.muted }, "能力切片"),
                        h(SliceBars, { data: result.by_capability })),
                      h("div", null, h("div", { style: s.muted }, "场景切片"),
                        h(SliceBars, { data: result.by_scenario_top })),
                    ),
                    h(
                      Button,
                      {
                        size: "small",
                        style: ALIGN_START,
                        onClick: function () {
                          props.onOpen(job.job_id);
                        },
                      },
                      "打开详情（逐题与产物）",
                    ),
                  ),
            ),
          };
        }),
      }),
    );
  }

  // ── job detail (three levels, inside one modal) ─────────────────────────

  function TaskDetailView(props) {
    var s = useStyles();
    var job = props.detail;
    var task = props.task;
    var [transcript, setTranscript] = useState(null);
    var [loadingMore, setLoadingMore] = useState(false);
    var attempt = task.attempt || 1;

    useEffect(
      function () {
        if (!task) return undefined;
        var alive = true;
        api
          .transcript(job.job_id, task.task_id, attempt, 0)
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
      [job.job_id, task.task_id, attempt],
    );

    function more() {
      if (!transcript || transcript.next_cursor === null) return;
      setLoadingMore(true);
      api
        .transcript(job.job_id, task.task_id, attempt, transcript.next_cursor)
        .then(function (page) {
          setTranscript(function (previous) {
            return Object.assign({}, page, {
              events: (previous.events || []).concat(page.events || []),
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

    var breakdown = task.automated_breakdown || [];
    var artifacts = task.artifacts || [];
    var downloads = task.downloads || [];

    return h(
      "div",
      { style: s.stack },
      h(
        "div",
        { style: s.row },
        h(Button, { size: "small", style: ALIGN_START, onClick: props.onBack }, "← 返回逐题列表"),
        h(Text, { strong: true }, task.name || task.task_id),
        h(Tag, { color: statusMeta(task.status).color }, statusMeta(task.status).text),
        h(Text, { style: s.tiny }, "第 " + attempt + " 次 · " + fmtNum(task.duration_s, 1) + "s"),
      ),
      task.failure_reason
        ? h(Alert, { type: "error", showIcon: true, message: "失败原因：" + task.failure_reason })
        : null,
      h(
        Descriptions,
        {
          size: "small",
          column: 2,
          bordered: true,
          styles: { label: FACT_LABEL_STYLE },
          items: [
            { key: "score", label: "得分", children: task.score === null ? "—" : fmtNum(task.score, 3) },
            { key: "grading", label: "判分方式", children: task.grading_type || "—" },
            { key: "labels", label: "标签", children: labelText(task.labels) },
            { key: "writes", label: "写回", children: "protocol " + (task.protocol_written || 0) + " · 带外 " + (task.out_of_band_count || 0) },
            { key: "model", label: "自报模型", children: (task.subject_model_reported || []).join("、") || "—" },
            { key: "from", label: "解析自", children: (task.resolved_from || []).join("、") || "—" },
          ],
        },
      ),
      h("div", null,
        h("div", { style: s.muted }, "判据逐项"),
        breakdown.length
          ? h(List, {
              size: "small",
              dataSource: breakdown,
              renderItem: function (item) {
                return h(List.Item, null,
                  h(Text, { style: s.mono }, JSON.stringify(item)));
              },
            })
          : h(Text, { style: s.tiny }, "没有逐项判分（非规则判分或未产出）")),
      props.sensitivity === "full" && task.rubric_excerpt
        ? h("div", null,
            h("div", { style: s.muted }, "评分依据（完整版）"),
            h("pre", { style: Object.assign({}, s.mono, { whiteSpace: "pre-wrap", margin: 0 }) }, task.rubric_excerpt))
        : null,
      props.sensitivity === "full" && (task.judge_notes || []).length
        ? h("div", null,
            h("div", { style: s.muted }, "判分备注（完整版）"),
            h(List, { size: "small", dataSource: task.judge_notes,
              renderItem: function (item) { return h(List.Item, null, h(Text, { style: s.mono }, JSON.stringify(item))); } }))
        : null,
      h("div", null,
        h("div", { style: s.muted }, "产物"),
        artifacts.length
          ? h(List, {
              size: "small",
              dataSource: artifacts,
              renderItem: function (item) {
                var link = downloads.filter(function (entry) {
                  return entry.path === item.path;
                })[0];
                return h(List.Item, {
                  actions: link
                    ? [h(Button, {
                        size: "small",
                        type: "link",
                        onClick: function () {
                          var href = link.href + "?path=" + encodeURIComponent(link.query.path);
                          downloadPath(href, item.path.split("/").pop());
                        },
                      }, "下载")]
                    : null,
                },
                h(Text, { style: s.mono }, item.path + " · " + item.size + "B · " + String(item.sha256).slice(0, 12)));
              },
            })
          : h(Text, { style: s.tiny },
              props.sensitivity === "full" ? "没有产物" : "产物清单在完整版里（shared 档不列）")),
      h("div", null,
        h("div", { style: s.row },
          h("span", { style: s.muted }, "轨迹时间线"),
          transcript ? h(Text, { style: s.tiny },
            "共 " + transcript.total_events + " 条 · 读入 " + (transcript.events || []).length +
            (transcript.damaged_events ? " · 损坏 " + transcript.damaged_events : "") +
            " · 状态 " + transcript.transcript_state) : null),
        transcript && (transcript.events || []).length
          ? h(
              "div",
              { style: Object.assign({}, s.mono, { maxHeight: 260, overflow: "auto", marginTop: 6 }) },
              transcript.events.map(function (event, index) {
                return h("div", { key: index, style: { padding: "2px 0" } },
                  h(Text, { style: s.tiny }, fmtFull(event.at) + "  "),
                  h(Text, null, event.kind),
                  event.tool ? h(Text, null, " · " + event.tool + " · " + (event.status || "")) : null,
                  event.steps ? h(Text, null, " · " + event.steps + " 步计划") : null,
                  event.chars ? h(Text, { style: s.tiny }, " · " + event.chars + " 字符") : null,
                  event.result_chars ? h(Text, { style: s.tiny }, " · 结果 " + event.result_chars + " 字符") : null);
              }),
            )
          : h(Text, { style: s.tiny },
              transcript ? "这次运行没有可读的轨迹（" + transcript.transcript_state + "）" : "读取中…"),
        transcript && transcript.next_cursor !== null
          ? h(Button, { size: "small", style: { marginTop: 6 }, loading: loadingMore, onClick: more },
              "再读 " + transcript.limit + " 条")
          : null),
    );
  }

  function labelText(labels) {
    if (!labels) return "—";
    var parts = [];
    ["scenario", "complexity", "environment"].forEach(function (key) {
      if (labels[key]) parts.push(labels[key]);
    });
    if (labels.modality) {
      parts.push(typeof labels.modality === "string" ? labels.modality : labels.modality.type);
    }
    if ((labels.capabilities || []).length) parts.push(labels.capabilities.join("/"));
    return parts.join(" · ") || "—";
  }

  function JobDetailModal(props) {
    var s = useStyles();
    var [detail, setDetail] = useState(null);
    var [error, setError] = useState(null);
    var [level, setLevel] = useState("job");
    var [task, setTask] = useState(null);
    var [sensitivity, setSensitivity] = useState("shared");
    var [report, setReport] = useState(null);
    var [reportFormat, setReportFormat] = useState("md");
    var [reporting, setReporting] = useState(false);

    useEffect(
      function () {
        if (!props.open || !props.jobId) return undefined;
        var alive = true;
        setDetail(null);
        setError(null);
        setLevel("job");
        setTask(null);
        setReport(null);
        api
          .detail(props.jobId, sensitivity)
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
      [props.open, props.jobId, sensitivity],
    );

    function openTask(taskId) {
      api
        .taskDetail(props.jobId, taskId, sensitivity)
        .then(function (result) {
          setTask(result);
          setLevel("task");
        })
        .catch(function (err) {
          message.error("单题详情读取失败：" + errOf(err).message);
        });
    }

    function makeReport() {
      setReporting(true);
      setReport(null);
      api
        .report(props.jobId, reportFormat, sensitivity)
        .then(function (result) {
          setReport(result);
        })
        .catch(function (err) {
          var info = errOf(err);
          message.error("报告生成失败：" + info.code + " " + info.message);
        })
        .then(function () {
          setReporting(false);
        });
    }

    var formatOptions = REPORT_FORMATS.map(function (format) {
      var disabled = format === "zip" && sensitivity !== "full";
      return {
        value: format,
        label: disabled ? format + "（仅完整版）" : format,
        disabled: disabled,
      };
    });

    function levelJob() {
      if (error) {
        return h(Alert, { type: "error", showIcon: true, message: error.code, description: error.message });
      }
      if (!detail) return h(Spin, null);
      var progress = detail.progress || { total: 0, by_status: {}, scored: 0 };
      var status = detail.status;
      var byStatus = progress.by_status || {};
      return h(
        "div",
        { style: s.stack },
        h(
          Descriptions,
          {
            size: "small",
            column: 2,
            bordered: true,
            styles: { label: FACT_LABEL_STYLE },
            items: [
              { key: "job", label: "任务", children: h(Text, { style: s.mono }, detail.job_id) },
              { key: "status", label: "状态", children: h(Tag, { color: statusMeta(status).color }, statusMeta(status).text) },
              { key: "submitter", label: "提交人", children: detail.submitter || "—" },
              { key: "product", label: "产品 / 目的", children: (detail.product || "—") + " / " + (detail.purpose || "—") },
              { key: "acp", label: "ACP 地址", children: h(Text, { style: s.mono }, detail.acp_url || "—") },
              {
                key: "window",
                label: "窗口",
                children: detail.window
                  ? windowLabel(detail.window.kind) + " · " + fmtFull(detail.window.not_before) +
                    (detail.window.not_after ? " → " + fmtFull(detail.window.not_after) : " → 无截止")
                  : "—",
              },
              { key: "created", label: "创建 / 开始", children: fmtFull(detail.created_at) + " / " + fmtFull(detail.started_at) },
              { key: "finished", label: "结束", children: fmtFull(detail.finished_at) },
              detail.error
                ? { key: "error", label: "错误", span: 2, children: h(Text, { type: "danger" }, detail.error) }
                : null,
            ].filter(Boolean),
          },
        ),
        h(
          "div",
          null,
          h("div", { style: s.muted }, "进度"),
          h(Progress, {
            // Finished out of total, not "reached a terminal state": a job whose
            // 15 tasks all failed is 0% done, and a full bar in success green
            // would say the opposite of what the row below it says.
            percent: progress.total
              ? Math.round(((byStatus.finished || 0) / progress.total) * 100)
              : 0,
            size: "small",
            strokeColor: byStatus.failed ? s.token.colorError : s.token.colorPrimary,
          }),
          h("div", { style: s.row },
            Object.keys(byStatus).sort().map(function (key) {
              var meta = statusMeta(key);
              return h(Tag, { key: key, color: meta.color, bordered: false }, meta.text + " " + byStatus[key]);
            }),
            h(Text, { style: s.tiny }, "计分 " + progress.scored + " / " + progress.total)),
        ),
        h(
          "div",
          { style: s.row },
          h(Text, { style: s.muted }, "总分"),
          h(Text, { style: s.mono }, fmtPct(detail.score && detail.score.mean)),
          h(Text, { style: s.tiny },
            detail.score
              ? "计分 " + detail.score.count + " 题 · 最高 " + fmtNum(detail.score.best, 3) +
                " · 最低 " + fmtNum(detail.score.worst, 3)
              : ""),
        ),
        h(
          "div",
          { style: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", gap: 16 } },
          h("div", null, h("div", { style: s.muted }, "场景切片"),
            h(SliceBars, { data: detail.slices && detail.slices.scenario })),
          h("div", null, h("div", { style: s.muted }, "能力切片"),
            h(SliceBars, { data: detail.slices && detail.slices.capability })),
        ),
        h("div", null,
          h("div", { style: s.muted }, "数据集来源"),
          (detail.sources || []).map(function (source) {
            return h("div", { key: source.dataset_id, style: s.row },
              h(Tag, { bordered: false }, source.dataset_kind),
              h(Text, { style: s.mono }, source.dataset_id),
              h(Text, { style: s.tiny }, source.task_count + " 题 · 由 " + source.requested_by + " 请求"));
          })),
        h(Divider, { style: { margin: "8px 0" } }),
        h(
          "div",
          { style: s.row },
          h("span", { style: s.muted }, "报告"),
          h(Select, {
            size: "small",
            style: { width: 170 },
            value: reportFormat,
            options: formatOptions,
            onChange: setReportFormat,
          }),
          h(Button, { size: "small", loading: reporting, onClick: makeReport }, "生成"),
          report
            ? h("span", { style: s.row },
                h(Text, { style: s.mono }, report.filename),
                h(Text, { style: s.tiny }, (report.size / 1024).toFixed(1) + " KB"),
                h(Button, {
                  size: "small",
                  type: "link",
                  onClick: function () {
                    var proxied = API + "/fetch?url=" + encodeURIComponent(report.url);
                    fetch(host.getApiUrl(proxied), {
                      headers: (function () {
                        var token = typeof host.getApiToken === "function" ? host.getApiToken() : "";
                        return token ? { Authorization: "Bearer " + token } : {};
                      })(),
                    })
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
                  },
                }, "下载"))
            : null,
        ),
        report
          ? h("div", { style: s.stack },
              h(Text, { style: s.tiny }, "sha256 " + report.sha256),
              h(Text, { style: s.tiny }, "过期 " + fmtFull(report.expires_at) + "（" + untilText(report.expires_at) + "）"))
          : null,
        h(Divider, { style: { margin: "8px 0" } }),
        h(
          Button,
          { type: "primary", onClick: function () { setLevel("tasks"); } },
          "看逐题（" + (detail.tasks || []).length + "）",
        ),
      );
    }

    function levelTasks() {
      if (!detail) return h(Spin, null);
      var rows = detail.tasks || [];
      var columns = [
        {
          title: "题目",
          dataIndex: "name",
          render: function (_, row) {
            return h(
              "div",
              { style: { display: "flex", flexDirection: "column" } },
              h(Text, { strong: true }, row.name || row.task_id),
              h(Text, { style: s.mono }, row.task_id),
            );
          },
        },
        { title: "能力/场景", dataIndex: "labels", width: 220,
          render: function (value) { return h(Text, { style: s.tiny }, labelText(value)); } },
        {
          title: "状态",
          dataIndex: "status",
          width: 96,
          render: function (value, row) {
            // Three of these are not job statuses at all: the runner records them
            // per task and they have no Chinese spelling, so they are shown as the
            // token the operator will grep for.
            var labels = { skipped: "跳过", no_artifacts: "无产物", missing: "缺失" };
            var colour = statusMeta(value).color;
            if (labels[value] || value === "failed") colour = "error";
            return h(Tooltip, { title: row.failure_reason || "" },
              h(Tag, { color: colour }, labels[value] || statusMeta(value).text));
          },
        },
        {
          title: "分数",
          dataIndex: "score",
          width: 80,
          render: function (value) { return h(Text, { style: s.mono }, value === null ? "—" : fmtNum(value, 3)); },
        },
        {
          title: "耗时",
          dataIndex: "duration_s",
          width: 80,
          render: function (value) { return h(Text, { style: s.mono }, fmtNum(value, 1) + "s"); },
        },
        { title: "写回", width: 96,
          render: function (_, row) {
            return h(Text, { style: s.tiny }, (row.protocol_written || 0) + " / " + (row.out_of_band_count || 0));
          } },
        {
          title: "",
          width: 72,
          render: function (_, row) {
            return h(Button, { size: "small", type: "link", onClick: function () { openTask(row.task_id); } }, "单题");
          },
        },
      ];
      return h(
        "div",
        { style: s.stack },
        h(Button, {
          size: "small",
          style: ALIGN_START,
          onClick: function () { setLevel("job"); },
        }, "← 返回概览"),
        h(Table, {
          size: "small",
          rowKey: "task_id",
          dataSource: rows,
          columns: columns,
          pagination: { pageSize: 15, size: "small" },
          scroll: { x: 900 },
        }),
      );
    }

    var title = "任务详情";
    if (detail) title = detail.purpose || "任务详情";
    return h(
      Modal,
      {
        open: props.open,
        onCancel: props.onClose,
        footer: null,
        width: 1080,
        style: { top: 24 },
        title: h(
          "div",
          { style: Object.assign({}, s.row, { justifyContent: "space-between" }) },
          h("div", { style: s.row },
            h(Text, { strong: true }, title),
            detail ? h(Tag, { style: s.mono }, shortId(detail.job_id)) : null,
            detail
              ? h(Button, {
                  size: "small",
                  type: "link",
                  onClick: function () {
                    var link = window.location.origin + window.location.pathname + "?app=pawbench-eval&job=" + props.jobId;
                    if (navigator.clipboard) {
                      navigator.clipboard.writeText(link);
                      message.success("本题链接已复制");
                    } else {
                      message.info(link);
                    }
                  },
                }, "复制本题链接")
              : null),
          h(
            "div",
            { style: s.row },
            h(Segmented, {
              size: "small",
              value: sensitivity,
              onChange: function (value) {
                setSensitivity(value);
                setLevel("job");
                setReport(null);
                // zip is only issued for the full tier, so carrying the choice
                // back into shared would make the next 生成 a guaranteed 400.
                if (value === "shared" && reportFormat === "zip") setReportFormat("md");
              },
              options: [
                { value: "shared", label: "shared" },
                { value: "full", label: "完整版" },
              ],
            }),
          ),
        ),
      },
      sensitivity === "full"
        ? h(Alert, {
            type: "warning",
            showIcon: true,
            style: { marginBottom: 12 },
            message: "完整版含评分依据与他人产物，对外只发 shared 版",
          })
        : null,
      level === "job" ? levelJob() : null,
      level === "tasks" ? levelTasks() : null,
      level === "task" && task
        ? h(TaskDetailView, {
            detail: detail || { job_id: props.jobId },
            task: task,
            sensitivity: sensitivity,
            onBack: function () {
              setLevel("tasks");
            },
          })
        : null,
    );
  }

  // ── datasets ────────────────────────────────────────────────────────────

  function DatasetSection(props) {
    var s = useStyles();
    var [editing, setEditing] = useState(null); // "view" | "upload" | "category" | null
    var [form, setForm] = useState({});
    var [busy, setBusy] = useState(false);
    var catalog = props.catalog;

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

    var columns = [
      {
        title: "数据集",
        dataIndex: "id",
        render: function (_, row) {
          return h(
            "div",
            { style: { display: "flex", flexDirection: "column" } },
            h(Text, { strong: true }, row.name || row.id),
            h(Text, { style: s.mono }, row.id + " · " + row.kind),
          );
        },
      },
      { title: "题数", dataIndex: "task_count", width: 70 },
      {
        title: "分类",
        dataIndex: "categories",
        width: 200,
        render: function (value) {
          if (!value || !value.length) return h(Text, { style: s.tiny }, "未分类");
          return h(Space, { size: 2, wrap: true },
            value.map(function (name) { return h(Tag, { key: name, bordered: false }, name); }));
        },
      },
      { title: "维护人", dataIndex: "owner", width: 110 },
      { title: "更新", dataIndex: "updated_at", width: 130,
        render: function (value) { return h(Text, { style: s.tiny }, fmtShort(value)); } },
      {
        title: "",
        width: 80,
        render: function (_, row) {
          var mine = !props.subject || row.owner === props.subject;
          var node = h(Button, { size: "small", type: "link", danger: true, disabled: !mine }, "删除");
          if (mine) {
            return h(Popconfirm, {
              title: "删除 " + row.id + "？",
              description: "跑过任务的删不掉，服务会拒绝。",
              okText: "删除",
              cancelText: "算了",
              onConfirm: function () { removeDataset(row); },
            }, node);
          }
          return h(Tooltip, { title: "由 " + row.owner + " 维护" }, node);
        },
      },
    ];

    var categoryRows = catalog.categories || [];
    var categoryColumns = [
      { title: "分类", dataIndex: "name" },
      { title: "数据集数", dataIndex: "dataset_count", width: 96 },
      { title: "创建者", dataIndex: "created_by", width: 120 },
      {
        title: "",
        width: 80,
        render: function (_, row) {
          var mine = !props.subject || row.created_by === props.subject;
          var node = h(Button, { size: "small", type: "link", danger: true, disabled: !mine }, "删除");
          if (mine) {
            return h(Popconfirm, {
              title: "删除分类 " + row.name + "？",
              description: "只删空分类，还有数据集挂着会被拒。",
              okText: "删除",
              cancelText: "算了",
              onConfirm: function () { removeCategory(row); },
            }, node);
          }
          return h(Tooltip, { title: "由 " + row.created_by + " 维护" }, node);
        },
      },
    ];

    function filterEditor() {
      var distribution = catalog.label_distribution || {};
      return h(
        "div",
        { style: s.stack },
        FILTER_KEYS.map(function (key) {
          var values = Object.keys(distribution[key] || {});
          if (!values.length) {
            return h(
              Field,
              { key: key, label: key, hint: "服务不提供该维度的分布，手填值" },
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
      Card,
      {
        title: "数据集",
        style: s.card,
        extra: h(
          Space,
          null,
          h(Button, { size: "small", onClick: startView }, "新建视图"),
          h(Button, { size: "small", onClick: startUpload }, "上传自定义集"),
          h(Button, {
            size: "small",
            onClick: function () {
              setForm({ name: "", description: "" });
              setEditing("category");
            },
          }, "分类管理"),
        ),
      },
      h(Table, {
        size: "small",
        rowKey: "id",
        dataSource: catalog.datasets || [],
        columns: columns,
        pagination: false,
        locale: { emptyText: h(Empty, { image: Empty.PRESENTED_IMAGE_SIMPLE, description: "还没有数据集" }) },
      }),
      h(
        Modal,
        {
          open: editing === "view",
          title: "新建视图（从内置语料切一片）",
          onCancel: function () { setEditing(null); },
          onOk: submitView,
          confirmLoading: busy,
          okText: "创建",
          width: 640,
        },
        h(Field, { label: "id", hint: "字母或数字开头，可含 . _ -，最长 80 位；会装进别人的选择器里"} ,
          h(Input, {
            value: form.id || "",
            onChange: function (event) { setForm(Object.assign({}, form, { id: event.target.value })); },
          })),
        h(Field, { label: "显示名" },
          h(Input, {
            value: form.name || "",
            onChange: function (event) { setForm(Object.assign({}, form, { name: event.target.value })); },
          })),
        h(Field, { label: "说明" },
          h(Input.TextArea, {
            rows: 2,
            value: form.description || "",
            onChange: function (event) { setForm(Object.assign({}, form, { description: event.target.value })); },
          })),
        h(Field, { label: "归档分类" },
          h(Select, {
            mode: "multiple",
            style: { width: "100%" },
            value: form.categories || [],
            options: categoryOptions,
            onChange: function (next) { setForm(Object.assign({}, form, { categories: next })); },
          })),
        h("div", { style: s.muted }, "过滤条件（至少一条）"),
        filterEditor(),
      ),
      h(
        Modal,
        {
          open: editing === "upload",
          title: "上传自定义任务包",
          onCancel: function () { setEditing(null); },
          onOk: submitUpload,
          confirmLoading: busy,
          okText: "上传",
          width: 640,
        },
        h(Field, { label: "id", hint: "字母或数字开头，可含 . _ -，最长 80 位"} ,
          h(Input, {
            value: form.id || "",
            onChange: function (event) { setForm(Object.assign({}, form, { id: event.target.value })); },
          })),
        h(Field, { label: "显示名" },
          h(Input, {
            value: form.name || "",
            onChange: function (event) { setForm(Object.assign({}, form, { name: event.target.value })); },
          })),
        h(Field, { label: "说明" },
          h(Input.TextArea, {
            rows: 2,
            value: form.description || "",
            onChange: function (event) { setForm(Object.assign({}, form, { description: event.target.value })); },
          })),
        h(Field, { label: "归档分类" },
          h(Select, {
            mode: "multiple",
            style: { width: "100%" },
            value: form.categories || [],
            options: categoryOptions,
            onChange: function (next) { setForm(Object.assign({}, form, { categories: next })); },
          })),
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
          onCancel: function () { setEditing(null); },
          footer: null,
          width: 720,
        },
        h(
          "div",
          { style: Object.assign({}, s.row, { marginBottom: 12 }) },
          h(Input, {
            placeholder: "新分类名",
            value: form.name || "",
            onChange: function (event) { setForm(Object.assign({}, form, { name: event.target.value })); },
            style: { width: 240 },
          }),
          h(Button, {
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
          }, "创建（同名幂等）"),
        ),
        h(Table, {
          size: "small",
          rowKey: "name",
          dataSource: categoryRows,
          columns: categoryColumns,
          pagination: false,
          locale: { emptyText: h(Empty, { image: Empty.PRESENTED_IMAGE_SIMPLE, description: "还没有分类" }) },
        }),
      ),
    );
  }

  // ── page ────────────────────────────────────────────────────────────────

  function Dashboard() {
    var s = useStyles();
    var [config, setConfig] = useState(null);
    var [probe, setProbe] = useState(null);
    var [probing, setProbing] = useState(false);
    var [settingsOpen, setSettingsOpen] = useState(false);
    var [catalog, setCatalog] = useState({ datasets: [], categories: [], label_distribution: {} });
    var [jobs, setJobs] = useState([]);
    var [loadError, setLoadError] = useState(null);
    var [detailJob, setDetailJob] = useState(null);

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
          // An unconfigured service is not an error to shout about: the panel
          // above already says so, and a red toast on every poll is noise.
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

    useEffect(function () {
      refreshConfig();
      runProbe();
    }, [refreshConfig, runProbe]);

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

    // A `?job=` in the URL opens that job's detail: the queue row's "复制本题
    // 链接" is only useful if the link lands somewhere.
    useEffect(
      function () {
        if (!ready) return;
        try {
          var params = new URLSearchParams(window.location.search);
          var job = params.get("job");
          if (job) setDetailJob(job);
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

    var body;
    if (!ready) {
      body = h(
        Card,
        { style: s.card },
        h(Empty, {
          image: Empty.PRESENTED_IMAGE_SIMPLE,
          description: h(
            "div",
            { style: s.stack },
            h(Text, null, "还没有连上评测服务"),
            h(Text, { style: s.tiny },
              "填一次服务地址和 token 就能用；token 只留在本机插件目录，页面拿不到。"),
          ),
        }),
        h("div", { style: { textAlign: "center", marginTop: 8 } },
          h(Button, { type: "primary", onClick: function () { setSettingsOpen(true); } }, "配置服务连接")),
      );
    } else {
      body = h(
        "div",
        { style: s.stack },
        h(SubmitSection, {
          catalog: catalog,
          onSubmitted: function () {
            refreshJobs();
          },
          onIdentity: onIdentity,
        }),
        h(QueueSection, {
          jobs: jobs,
          subject: config.subject,
          onRefresh: refreshJobs,
          onOpen: setDetailJob,
        }),
        h(ResultsSection, { jobs: jobs, onOpen: setDetailJob }),
        h(DatasetSection, {
          catalog: catalog,
          subject: config.subject,
          onRefresh: refreshCatalog,
        }),
      );
    }

    return h(
      "div",
      { style: { padding: 16, display: "flex", flexDirection: "column", gap: 16 } },
      h(
        Card,
        { style: s.card, bodyStyle: { padding: 12 } },
        h(ConnectionBar, {
          config: config,
          probe: probe,
          probing: probing,
          onProbe: function () {
            runProbe();
            refreshConfig();
          },
          onEdit: function () {
            setSettingsOpen(true);
          },
        }),
      ),
      loadError
        ? h(Alert, {
            type: "error",
            showIcon: true,
            closable: true,
            onClose: function () { setLoadError(null); },
            message: loadError.code,
            description: loadError.message,
          })
        : null,
      body,
      h(ConnectionModal, {
        open: settingsOpen,
        config: config,
        probe: probe,
        onClose: function () { setSettingsOpen(false); },
        onSaved: function () {
          refreshConfig();
          refreshCatalog();
          refreshJobs();
        },
      }),
      h(JobDetailModal, {
        open: Boolean(detailJob),
        jobId: detailJob,
        onClose: function () {
          setDetailJob(null);
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
