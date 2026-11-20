// 重新生成派生物：*.dot → *.svg → dashboard.html
// .dot 是唯一真源；不要手改 .svg 或 dashboard.html。
//
//   npm i --prefix /tmp/pawbench-dot @viz-js/viz
//   node pal_sdd/feat_acp_remote_eval/architecture/render.mjs
//
// 依赖装在仓库外的临时目录，避免给这个 Python 仓库引入 node 依赖。
// 换位置时设 VIZ_PKG_BASE 指向含 node_modules 的目录。
import { createRequire } from "node:module";
import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const require = createRequire(join(process.env.VIZ_PKG_BASE || "/tmp/pawbench-dot", "package.json"));
const { instance } = require("@viz-js/viz");

const VIEWS = [
  {
    id: "arch",
    tab: "架构图 · 边界与复用",
    file: "pawbench_acp_boundary",
    question: "两者是什么关系？",
    note: "扩展，不是分叉。整个特性对核心的依赖只有 3 条绿边（BaseAgent / TaskLoader / 判分 helper），核心源码与共享依赖零改动。灰虚线是「绕过不调用」：CLI 编排、容器环境、AgentFactory 注册、grade_task 入口。红虚线是尚未建成的看板（M3）、MCP + 出题 skill（M4）与判分沙箱，不是现状能力。",
  },
  {
    id: "flow",
    tab: "流程图 · 两条链路对比",
    file: "eval_flow_local_vs_remote",
    question: "同一道题，两条链路各走什么步骤？",
    note: "左=原有本地链路，右=新增远端链路，中列标出该阶段的差异性质。②选题与⑧判分语义完全复用；④运行环境是根本差异（我们提供环境 → 对方自带环境 BYO），⑤⑥⑦因此全部改写；⑩是这条差异的代价：结果按 by_environment 单独分档。",
  },
  {
    id: "seq",
    tab: "流程图 · 远端单题下钻",
    file: "remote_attempt_sequence",
    question: "文件怎么过去、产物怎么回来、分怎么打？",
    note: "紫边是跨信任边界的两条唯一通道：ACP 下发 manifest，HTTP 数据面回收产物。第 8 步（对方机器内部执行）对我们不可观测，只有 ACP session/update 与最终上传可见。第 12 步的 exec 目前仍在服务进程内 —— 判分沙箱未建，这是已知缺口而非现状保障。",
  },
];

// 浏览器实测：CJK 字形比 graphviz 内置度量略宽，默认 margin 会让文字压到边框外。
// 各 .dot 里的 node margin 已据此放宽；改标签后请重跑本脚本并复核最长的那几行。
function renderDiagrams(viz) {
  return readdirSync(here)
    .filter((name) => name.endsWith(".dot"))
    .map((name) => {
      const svg = viz.renderString(readFileSync(join(here, name), "utf8"), { format: "svg" });
      const out = join(here, name.replace(/\.dot$/, ".svg"));
      writeFileSync(out, svg);
      const size = svg.match(/width="(\d+)pt" height="(\d+)pt"/);
      return { name, size: size ? `${size[1]}x${size[2]}pt` : "?" };
    });
}

function inlineSvg(file) {
  return readFileSync(join(here, `${file}.svg`), "utf8")
    .replace(/<\?xml[^>]*\?>\s*/, "")
    .replace(/<!DOCTYPE[^>]*>\s*/, "");
}

function buildDashboard() {
  const inputs = VIEWS.map(
    (v, i) => `
  <input type="radio" name="tab" id="tab-${v.id}" class="tabin"${i === 0 ? " checked" : ""}>
  <input type="checkbox" id="zoom-${v.id}" class="zomin">`,
  ).join("");

  const labels = VIEWS.map(
    (v) => `<label for="tab-${v.id}" class="tablab" data-t="${v.id}">${v.tab}</label>`,
  ).join("");

  const bodies = VIEWS.map(
    (v) => `
  <section class="panel" data-p="${v.id}">
    <div class="qbar"><span class="q">${v.question}</span>
      <label for="zoom-${v.id}" class="zoombtn">切换 1:1 / 适应宽度</label></div>
    <p class="note">${v.note}</p>
    <div class="canvas">${inlineSvg(v.file)}</div>
    <p class="src">canonical 源：<code>pal_sdd/feat_acp_remote_eval/architecture/${v.file}.dot</code>　派生：<code>${v.file}.svg</code></p>
  </section>`,
  ).join("");

  const css = `
.pba{--ink:#1f2933;--mut:#6b7280;--line:#d9e2ec;--org:#b26a00;--grn:#2e7d32;
 font-family:-apple-system,"PingFang SC","Helvetica Neue",Helvetica,Arial,sans-serif;color:var(--ink);
 max-width:1200px;margin:0 auto;padding:4px 2px 18px;line-height:1.6}
.pba *{box-sizing:border-box}
.pba h2{font-size:19px;margin:2px 0 6px}
.pba .sub{color:var(--mut);font-size:12.5px;margin:0 0 12px}
.pba .key{border:1px solid var(--line);border-left:3px solid var(--grn);border-radius:8px;
 padding:10px 13px;background:#f7fbf8;font-size:13px;margin:0 0 14px}
.pba .key b{color:var(--grn)}
.pba .key code{background:#eef2f7;padding:1px 4px;border-radius:4px;font-size:12px}
.pba .tabin,.pba .zomin{position:absolute;opacity:0;pointer-events:none}
.pba .tabs{display:flex;gap:6px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:8px;margin-bottom:12px}
.pba .tablab{cursor:pointer;font-size:13px;padding:6px 12px;border:1px solid var(--line);
 border-radius:8px;background:#fff;color:var(--mut);user-select:none}
.pba .tablab:hover{border-color:#9aa5b1;color:var(--ink)}
.pba .panel{display:none}
.pba .qbar{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:6px}
.pba .q{font-size:14.5px;font-weight:600}
.pba .zoombtn{cursor:pointer;font-size:12px;padding:4px 10px;border:1px solid var(--line);
 border-radius:6px;background:#fff;color:var(--mut);white-space:nowrap}
.pba .zoombtn:hover{border-color:#9aa5b1;color:var(--ink)}
.pba .note{font-size:12.8px;color:#3e4c59;background:#fafbfc;border:1px solid var(--line);
 border-radius:8px;padding:9px 12px;margin:0 0 10px}
.pba .canvas{border:1px solid var(--line);border-radius:12px;background:#fff;padding:10px;overflow:auto}
.pba .canvas svg{width:100%;height:auto;display:block}
.pba .src{font-size:11.5px;color:var(--mut);margin:8px 0 0}
.pba .src code{background:#f4f6f8;padding:1px 4px;border-radius:4px}
.pba .legend{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;color:#3e4c59;
 border-top:1px solid var(--line);margin-top:16px;padding-top:10px}
.pba .legend i{display:inline-block;width:22px;height:0;border-top:2.5px solid;vertical-align:middle;margin-right:5px}
.pba .foot{font-size:11.8px;color:var(--mut);margin-top:10px}
${VIEWS.map(
  (v) => `#tab-${v.id}:checked ~ .tabs .tablab[data-t="${v.id}"]{background:#fff4e5;border-color:#e08a00;color:var(--org);font-weight:600}
#tab-${v.id}:checked ~ .panel[data-p="${v.id}"]{display:block}
#zoom-${v.id}:checked ~ .panel[data-p="${v.id}"] .canvas svg{width:auto;height:auto}
#zoom-${v.id}:checked ~ .panel[data-p="${v.id}"] .zoombtn{background:#fff4e5;border-color:#e08a00;color:var(--org)}`,
).join("\n")}
`;

  return `<div class="pba">
<style>${css}</style>
<h2>PawBench × acp-remote-eval：架构与流程</h2>
<p class="sub">视图状态：current state · 分支 feat/acp-remote-eval · 2026-11-11 · 代码已在盘上但未 commit · 证据均标注 path:line</p>
<div class="key"><b>一句话结论：</b>acp-remote-eval 是 PawBench 的<b>旁挂扩展</b>，不是改造或分叉。它复用核心的 <code>BaseAgent</code> 生命周期、<code>TaskLoader</code> 题库格式、<code>grader</code> 判分语义共 3 处；把「一次性 CLI + 我们提供的容器」换成「常驻服务 + 对方自带环境（BYO）+ 自建 HTTP 数据面」。<code>run_bench.py</code> 不 import 它，它也不 import CLI —— 只跑本地 benchmark 的安装完全不受影响。</div>
${inputs}
<div class="tabs">${labels}</div>
${bodies}
<div class="legend">
  <span><i style="border-color:#2e7d32"></i>复用核心（3 处）</span>
  <span><i style="border-color:#9aa5b1;border-top-style:dashed"></i>绕过 / 替换，不调用</span>
  <span><i style="border-color:#c47000"></i>新增内部链路</span>
  <span><i style="border-color:#7e57c2"></i>跨信任边界</span>
  <span><i style="border-color:#c62828;border-top-style:dashed"></i>尚未建成（目标态）</span>
</div>
<p class="foot">图由 <code>system-modeler</code> + <code>flow-visualizer</code> 场景技能产出，格式基础 <code>graphviz</code>；.dot 为唯一真源，.svg 与本页面均为派生物。重新生成见同目录 README.md。</p>
</div>`;
}

const viz = await instance();
for (const { name, size } of renderDiagrams(viz)) {
  console.log(`rendered ${name} -> ${name.replace(/\.dot$/, ".svg")} (${size})`);
}
const html = buildDashboard();
writeFileSync(join(here, "dashboard.html"), html);
console.log(`built dashboard.html (${html.length} bytes)`);