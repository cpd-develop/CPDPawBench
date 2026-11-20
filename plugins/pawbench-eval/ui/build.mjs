/**
 * Build the dashboard into the one file the host loads.
 *
 * The host fetches `ui/dist/index.js`, wraps it in a Blob and `import()`s it, so
 * the output has to be a single ESM file with **no bare imports at all** — a
 * Blob URL has no import map, and `import React from "react"` would fail at
 * runtime rather than at build time.  React, antd and the icon set therefore
 * come out of `window.QwenPaw.host` (see `src/host/`), and the three choices
 * below are what enforce that:
 *
 * - `jsx: "transform"` + `jsxFactory: "__h"` + `inject`: JSX compiles to calls
 *   on a factory function esbuild inserts into every file that needs it.  No
 *   module resolution is involved, so nothing can smuggle in a package.
 * - CSS is loaded as *text* and injected as a `<style>` at runtime, because the
 *   host loads one file and a sibling `index.css` would never be requested.
 * - `sourcesContent: false` keeps the bundle free of this repo's paths.
 */

import { build, context } from "esbuild";
import { mkdir } from "node:fs/promises";

const watch = process.argv.includes("--watch");

/** @type {import('esbuild').BuildOptions} */
const options = {
  entryPoints: ["src/index.tsx"],
  outfile: "index.js",
  bundle: true,
  format: "esm",
  target: ["es2020"],
  platform: "browser",
  jsx: "transform",
  jsxFactory: "__h",
  jsxFragment: "__Fragment",
  inject: ["src/host/jsx.ts"],
  loader: { ".css": "text" },
  // Keep Chinese as Chinese: an escaped bundle is unreadable in review, and a
  // test that greps the build output for a label needs the label to be there.
  charset: "utf8",
  legalComments: "none",
  sourcemap: false,
  logLevel: "info",
  metafile: false,
};

// The host loads `ui/index.js` and nothing else: the manifest points at it,
// and it is fetched again on every page load, so a rebuild is live without
// restarting the console.
await mkdir(".", { recursive: true });

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
  console.log("[pawbench-eval] watching src/ …");
} else {
  await build(options);
  console.log("[pawbench-eval] wrote ui/index.js");
}
