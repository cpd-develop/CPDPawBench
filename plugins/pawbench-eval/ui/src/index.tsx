/**
 * Entry point: inject the stylesheet, then register the route.
 *
 * The host fetches this bundle, wraps it in a Blob and `import()`s it, so there
 * is no `<link>` to add and no chance to run before the module evaluates.  The
 * styles therefore arrive injected — the design system's token file first (it
 * defines every custom property), then its atoms, then this page's rules — in
 * one `<style>` element appended to `<head>`.
 *
 * Registration is checked rather than assumed: a host version without
 * `registerRoutes` produces a console line instead of a half-mounted page.
 */

import tokenCss from "./designsys/colors_and_type.css";
import componentCss from "./designsys/components.css";
import pageCss from "./styles.css";

import { host } from "./host/sdk";
import { Shell } from "./shell";

const STYLE_ID = "pawbench-eval-styles";

function injectStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = [tokenCss, componentCss, pageCss].join("\n");
  document.head.appendChild(style);
}

function main(): void {
  const sdk = window.QwenPaw;
  if (!sdk?.host || typeof sdk.registerRoutes !== "function") {
    console.error("[pawbench-eval] window.QwenPaw host SDK is not ready");
    return;
  }
  // Touch the accessor once so a missing host fails here, with one message,
  // instead of inside a render pass that React will retry.
  host();
  injectStyles();

  sdk.registerRoutes("pawbench-eval", [
    {
      path: "/apps/pawbench-eval",
      component: Shell,
      label: "PawBench 评测",
      icon: "🧪",
      priority: 60,
    },
  ]);
}

main();
