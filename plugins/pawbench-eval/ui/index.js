// src/host/jsx.ts
var React = window.QwenPaw?.host?.React;
var __h = React.createElement;
var __Fragment = React.Fragment;

// src/designsys/colors_and_type.css
var colors_and_type_default = '/**\n * TraeWork design library tokens\n * Light-mode canonical tokens in parser-friendly standard structure.\n *\n * Source of truth:\n * - /Users/bytedance/Desktop/样板间/TraeWork skill.md\n *\n * Notes:\n * - Token values are preserved from the current TraeWork Light system.\n * - Added numeric tokens use direct values, e.g. --radius-12: 12px.\n * - Component HTML should reference these canonical token names.\n */\n\n/* @dual-theme: light default + dark override (data-theme="dark" re-points semantic color tokens) */\n/* @group-priority: radius, spacers, font, body, heading, code, bg, bg-brand, text, icon, border, accent, status, brand */\n\n:root {\n  /* radius — 三档纪律（2026-11-04 收敛）\n     12 = 卡片 / 弹窗 / 面板；8 = 按钮 / 输入 / 标签；4..6 = 标签 / 小控件。\n     0/2/10/16/20/24/32/full 与 xs..xl 别名已移除：直角写 CSS 原生 0，\n     原圆形 / 胶囊一律改用 --radius-4。 */\n  --radius-4: 4px;\n  --radius-6: 6px;\n  --radius-8: 8px;\n  --radius-12: 12px;\n  --border-width-default: 1px;\n\n  /* spacers */\n  --spacer-0: 0px;\n  --spacer-2: 2px;\n  --spacer-3: 3px;\n  --spacer-4: 4px;\n  --spacer-6: 6px;\n  --spacer-8: 8px;\n  --spacer-10: 10px;\n  --spacer-12: 12px;\n  --spacer-16: 16px;\n  --spacer-20: 20px;\n  --spacer-24: 24px;\n  --spacer-32: 32px;\n  --spacer-40: 40px;\n  --spacer-48: 48px;\n  --spacer-64: 64px;\n\n  /* icon sizes */\n  --icon-size-12: 12px;\n  --icon-size-14: 14px;\n  --icon-size-16: 16px;\n  --icon-size-20: 20px;\n  --icon-size-24: 24px;\n\n  /* font */\n  --font-family-default: "SF Pro Text", "PingFang SC", system-ui, "Segoe UI", Roboto;\n  --font-family-heading: var(--font-family-default);\n  --font-family-metric: var(--font-family-mono);\n  --font-family-mono: "JetBrains Mono", ui-monospace, Menlo, Consolas;\n  --font-weight-default: 400;\n  --font-weight-code: 450;\n  --font-weight-medium: 500;\n  --font-weight-strong: 600;\n  --font-family-base: var(--font-family-default);\n  --font-family-heading-alias: var(--font-family-heading);\n  --font-family-mono-alias: var(--font-family-mono);\n\n  /* body */\n  --body-xs-font-family: var(--font-family-default);\n  --body-xs-font-size: 10px;\n  --body-xs-font-weight: 400;\n  --body-xs-line-height: 14px;\n  --body-xs-letter-spacing: 0;\n  --body-xs-strong-font-family: var(--font-family-default);\n  --body-xs-strong-font-size: 10px;\n  --body-xs-strong-font-weight: 500;\n  --body-xs-strong-line-height: 14px;\n  --body-xs-strong-letter-spacing: 0;\n  --body-sm-font-family: var(--font-family-default);\n  --body-sm-font-size: 11px;\n  --body-sm-font-weight: 400;\n  --body-sm-line-height: 16px;\n  --body-sm-letter-spacing: 0;\n  --body-sm-strong-font-family: var(--font-family-default);\n  --body-sm-strong-font-size: 11px;\n  --body-sm-strong-font-weight: 500;\n  --body-sm-strong-line-height: 16px;\n  --body-sm-strong-letter-spacing: 0;\n  --body-md-font-family: var(--font-family-default);\n  --body-md-font-size: 12px;\n  --body-md-font-weight: 400;\n  --body-md-line-height: 18px;\n  --body-md-letter-spacing: 0;\n  --body-md-strong-font-family: var(--font-family-default);\n  --body-md-strong-font-size: 12px;\n  --body-md-strong-font-weight: 500;\n  --body-md-strong-line-height: 18px;\n  --body-md-strong-letter-spacing: 0;\n  --body-base-font-family: var(--font-family-default);\n  --body-base-font-size: 14px;\n  --body-base-font-weight: 400;\n  --body-base-line-height: 20px;\n  --body-base-letter-spacing: -0.02em;\n  --body-base-strong-font-family: var(--font-family-default);\n  --body-base-strong-font-size: 14px;\n  --body-base-strong-font-weight: 500;\n  --body-base-strong-line-height: 20px;\n  --body-base-strong-letter-spacing: -0.02em;\n  --body-lg-font-family: var(--font-family-default);\n  --body-lg-font-size: 18px;\n  --body-lg-font-weight: 400;\n  --body-lg-line-height: 28px;\n  --body-lg-letter-spacing: -0.02em;\n\n  /* heading */\n  --heading-3xs-font-family: var(--font-family-default);\n  --heading-3xs-font-size: 11px;\n  --heading-3xs-font-weight: 600;\n  --heading-3xs-line-height: 16px;\n  --heading-3xs-letter-spacing: 0;\n  --heading-2xs-font-family: var(--font-family-default);\n  --heading-2xs-font-size: 12px;\n  --heading-2xs-font-weight: 600;\n  --heading-2xs-line-height: 18px;\n  --heading-2xs-letter-spacing: 0;\n  --heading-xs-font-family: var(--font-family-default);\n  --heading-xs-font-size: 13px;\n  --heading-xs-font-weight: 600;\n  --heading-xs-line-height: 20px;\n  --heading-xs-letter-spacing: 0;\n  --heading-sm-font-family: var(--font-family-default);\n  --heading-sm-font-size: 16px;\n  --heading-sm-font-weight: 600;\n  --heading-sm-line-height: 24px;\n  --heading-sm-letter-spacing: 0;\n  --heading-md-font-family: var(--font-family-heading);\n  --heading-md-font-size: 20px;\n  --heading-md-font-weight: 600;\n  --heading-md-line-height: 28px;\n  --heading-md-letter-spacing: 0;\n  --heading-lg-font-family: var(--font-family-heading);\n  --heading-lg-font-size: 22px;\n  --heading-lg-font-weight: 600;\n  --heading-lg-line-height: 30px;\n  --heading-lg-letter-spacing: 0;\n  --heading-xl-font-family: var(--font-family-heading);\n  --heading-xl-font-size: 24px;\n  --heading-xl-font-weight: 600;\n  --heading-xl-line-height: 32px;\n  --heading-xl-letter-spacing: 0;\n  --heading-2xl-font-family: var(--font-family-heading);\n  --heading-2xl-font-size: 28px;\n  --heading-2xl-font-weight: 600;\n  --heading-2xl-line-height: 36px;\n  --heading-2xl-letter-spacing: 0;\n  --heading-3xl-font-family: var(--font-family-heading);\n  --heading-3xl-font-size: 32px;\n  --heading-3xl-font-weight: 600;\n  --heading-3xl-line-height: 40px;\n  --heading-3xl-letter-spacing: 0;\n  --heading-display-font-family: var(--font-family-heading);\n  --heading-display-font-size: 52px;\n  --heading-display-font-weight: 600;\n  --heading-display-line-height: 60px;\n  --heading-display-letter-spacing: -0.03em;\n  --heading-display-sm-font-family: var(--font-family-heading);\n  --heading-display-sm-font-size: 40px;\n  --heading-display-sm-font-weight: 600;\n  --heading-display-sm-line-height: 48px;\n  --heading-display-sm-letter-spacing: -0.02em;\n\n  /* code */\n  --code-editor-font-family: var(--font-family-mono);\n  --code-editor-font-size: 13px;\n  --code-editor-font-weight: 450;\n  --code-editor-line-height: 20px;\n  --code-terminal-font-family: var(--font-family-mono);\n  --code-terminal-font-size: 12px;\n  --code-terminal-font-weight: 450;\n  --code-terminal-line-height: 18px;\n  --code-text: #17181A;\n  --code-doc: #8393A3;\n  --code-link: #2F74FF;\n  --code-number: #E54595;\n  --code-action: #5F36B2;\n  --code-instruction: #B15EF2;\n  --code-function: #FF5D4D;\n  --code-constant: #175CE6;\n  --code-parameter: #4DA621;\n  --code-attribute: #C99100;\n  --code-tag: #E24864;\n\n  /* bg */\n  --bg-base-default: #FFFFFF;\n  --bg-base-secondary: #F5F5F5;\n  --bg-page: #FEFEFF; /* king_2026 2026-11-05: 示例页画布(近白), 深色沿用画布深色 */\n  --bg-card-hover: #F6F6F6; /* king_2026 2026-11-06: 卡片 hover 灰（用户指定），替代原 hover 阴影+描边加深 */\n  --bg-base-tertiary: #E5E5E5;\n  --bg-overlay-l1: rgba(115, 115, 115, 0.08);\n  --bg-overlay-l2: rgba(115, 115, 115, 0.12);\n  --bg-overlay-l3: rgba(115, 115, 115, 0.16);\n  --bg-overlay-l4: rgba(115, 115, 115, 0.20);\n  --bg-white: #FFFFFF;\n  --bg-menu: #FFFFFF;\n  --bg-tooltip: #FFFFFF;\n  --bg-invert: #262626;\n  --bg-invert-hover: #404040;\n  --bg-invert-active: #171717;\n  --bg-invert-disabled: rgba(115, 115, 115, 0.20);\n  --color-background: var(--bg-base-default);\n  --color-surface: var(--bg-base-secondary);\n  --color-surface-variant: var(--bg-base-tertiary);\n  --color-overlay-1: var(--bg-overlay-l1);\n  --color-overlay-2: var(--bg-overlay-l2);\n  --color-overlay-3: var(--bg-overlay-l3);\n  --color-overlay-4: var(--bg-overlay-l4);\n  --color-card: var(--bg-base-secondary);\n  --color-tooltip: var(--bg-tooltip);\n  --color-menu: var(--bg-menu);\n\n  /* bg-brand */\n  --bg-brand: #4B3FE3;\n  --bg-brand-hover: #6A6FFF;\n  --bg-brand-active: #3F31C6;\n  --bg-brand-disabled: rgba(75, 63, 227, 0.22);\n  --bg-brand-popup: rgba(170, 183, 255, 0.36);\n  --color-primary: var(--bg-brand);\n  --color-primary-hover: var(--bg-brand-hover);\n  --color-primary-disabled: var(--bg-brand-disabled);\n  --color-primary-soft: var(--bg-brand-popup);\n  --color-accent: var(--bg-brand);\n\n  /* text */\n  --text-default: #171717;\n  --text-default-hover: #262626;\n  --text-default-active: #262626;\n  --text-secondary: #404040;\n  --text-secondary-hover: #171717;\n  --text-secondary-active: #171717;\n  --text-tertiary: #737373;\n  --text-disabled: #A1A1A1;\n  --text-onbrand: #FFFFFF;\n  --text-onaccent: #FFFFFF;\n  --text-white: #FFFFFF;\n  --color-foreground: var(--text-default);\n  --color-foreground-hover: var(--text-default-hover);\n  --color-on-surface: var(--text-default);\n  --color-on-surface-variant: var(--text-secondary);\n  --color-muted-foreground: var(--text-secondary);\n  --color-disabled-foreground: var(--text-disabled);\n  --color-on-primary: var(--text-onbrand);\n  --text-brand: #4B3FE3;\n  --text-brand-hover: #6A6FFF;\n  --text-brand-active: #3F31C6;\n\n  /* icon */\n  --icon-default: #262626;\n  --icon-default-hover: #171717;\n  --icon-default-active: #171717;\n  --icon-secondary: #404040;\n  --icon-secondary-hover: #262626;\n  --icon-secondary-active: #262626;\n  --icon-tertiary: #737373;\n  --icon-disabled: #A1A1A1;\n  --icon-onbrand: #FFFFFF;\n  --icon-onaccent: #FFFFFF;\n  --icon-white: #FFFFFF;\n  --icon-brand: #4B3FE3;\n  --icon-brand-hover: #6A6FFF;\n\n  /* border */\n  --border-neutral-l1: rgba(115, 115, 115, 0.12);\n  --border-neutral-l2: rgba(115, 115, 115, 0.18);\n  --border-neutral-l3: rgba(115, 115, 115, 0.36);\n  --border-contrast: #000000;\n  --border-brand: #4B3FE3;\n  --color-border: var(--border-neutral-l1);\n  --color-border-strong: var(--border-neutral-l2);\n  --color-border-stronger: var(--border-neutral-l3);\n  --color-border-contrast: var(--border-contrast);\n  --color-outline: var(--border-neutral-l1);\n\n  /* accent */\n  --accent-teal: #00B983;\n  --accent-coral: #FF6B45;\n  --accent-amber: #F2A90C;\n  --accent-lime: #5FC000;\n  --accent-cyan: #00B6F5;\n  --accent-blue: #3F85FF;\n  --accent-magenta: #F53CFF;\n  --accent-violet: #9570FF;\n  --accent-slate: #747E94;\n\n  /* status */\n  --status-primary-default: #2F74FF;\n  --status-primary-hover: #4C88FF;\n  --status-primary-active: #1759DD;\n  --status-primary-surface-l1: rgba(47, 116, 255, 0.12);\n  --status-primary-surface-l2: rgba(47, 116, 255, 0.18);\n  --status-primary-surface-l3: rgba(47, 116, 255, 0.36);\n  --status-success-default: #15A877;\n  --status-success-hover: #2FB287;\n  --status-success-active: #1E8B56;\n  --status-success-surface-l1: rgba(64, 176, 139, 0.12);\n  --status-success-surface-l2: rgba(64, 176, 139, 0.18);\n  --status-success-surface-l3: rgba(64, 176, 139, 0.36);\n  --status-alert-default: #FEA900;\n  --status-alert-hover: #FFB700;\n  --status-alert-active: #E59100;\n  --status-alert-surface-l1: rgba(254, 169, 0, 0.14);\n  --status-alert-surface-l2: rgba(254, 169, 0, 0.20);\n  --status-alert-surface-l3: rgba(254, 169, 0, 0.36);\n  --status-warning-default: #E27900;\n  --status-warning-hover: #F39A35;\n  --status-warning-active: #C46F11;\n  --status-warning-surface-l1: rgba(226, 121, 0, 0.12);\n  --status-warning-surface-l2: rgba(226, 121, 0, 0.16);\n  --status-warning-surface-l3: rgba(226, 121, 0, 0.36);\n  --status-error-default: #E8463A;\n  --status-error-hover: #EA574C;\n  --status-error-active: #C9382F;\n  --status-error-surface-l1: rgba(232, 70, 58, 0.12);\n  --status-error-surface-l2: rgba(232, 70, 58, 0.16);\n  --status-error-surface-l3: rgba(232, 70, 58, 0.36);\n  --color-info: var(--status-primary-default);\n  --color-success: var(--status-success-default);\n  --color-warning: var(--status-warning-default);\n  --color-error: var(--status-error-default);\n  --color-error-soft: var(--status-error-surface-l1);\n\n  /* brand */\n  --brand-50: #F2F7FF;\n  --brand-100: #E5EAFF;\n  --brand-200: #CFD8FF;\n  --brand-300: #AAB7FF;\n  --brand-400: #8894FF;\n  --brand-500: #6A6FFF;\n  --brand-600: #4B3FE3;\n  --brand-700: #3F31C6;\n  --brand-800: #2C2290;\n  --brand-900: #1A1759;\n  --brand-950: #010109;\n  --brand-grey-50: #FAFAFA;\n  --brand-grey-100: #F5F5F5;\n  --brand-grey-200: #E5E5E5;\n  --brand-grey-300: #D4D4D4;\n  --brand-grey-400: #A1A1A1;\n  --brand-grey-500: #737373;\n  --brand-grey-600: #525252;\n  --brand-grey-700: #404040;\n  --brand-grey-800: #262626;\n  --brand-grey-900: #171717;\n  --brand-grey-950: #0A0A0A;\n  --brand-green-100: var(--brand-50);\n  --brand-green-200: var(--brand-100);\n  --brand-green-300: var(--brand-200);\n  --brand-green-400: var(--brand-300);\n  --brand-green-500: var(--brand-600);\n  --brand-green-600: var(--brand-500);\n  --brand-green-700: var(--brand-700);\n  --brand-green-800: var(--brand-800);\n  --brand-green-900: var(--brand-900);\n  --brand-green-1000: var(--brand-950);\n  --brand-red-100: #FFE5E5;\n  --brand-red-200: #FFCCCC;\n  --brand-red-300: #FFB2B2;\n  --brand-red-400: #FF9999;\n  --brand-red-500: #FF8080;\n  --brand-red-600: #FF6464;\n  --brand-red-700: #E63737;\n  --brand-red-800: #CB1010;\n  --brand-red-900: #8F0505;\n  --brand-red-1000: #4D0000;\n  --brand-yellow-100: #FFF6E5;\n  --brand-yellow-200: #FFECCC;\n  --brand-yellow-300: #FFE3B2;\n  --brand-yellow-400: #FFDA99;\n  --brand-yellow-500: #FFD080;\n  --brand-yellow-600: #FFC864;\n  --brand-yellow-700: #E6A637;\n  --brand-yellow-800: #CB8710;\n  --brand-yellow-900: #8F5C05;\n  --brand-yellow-1000: #4D3000;\n  --brand-blue-100: #E5F3FF;\n  --brand-blue-200: #CCE6FF;\n  --brand-blue-300: #B2DAFF;\n  --brand-blue-400: #99CEFF;\n  --brand-blue-500: #80C1FF;\n  --brand-blue-600: #64B4FF;\n  --brand-blue-700: #3792E6;\n  --brand-blue-800: #1071CB;\n  --brand-blue-900: #054C8F;\n  --brand-blue-1000: #00284D;\n  --brand-purple-100: #E8E5FF;\n  --brand-purple-200: #D2CCFF;\n  --brand-purple-300: #BBB2FF;\n  --brand-purple-400: #A599FF;\n  --brand-purple-500: #8E80FF;\n  --brand-purple-600: #7864FF;\n  --brand-purple-700: #4C37E6;\n  --brand-purple-800: #2610CB;\n  --brand-purple-900: #15058F;\n  --brand-purple-1000: #09004D;\n  --brand-neutral-grey-100: #F2F2F2;\n  --brand-neutral-grey-200: #E3E3E3;\n  --brand-neutral-grey-300: #D6D6D6;\n  --brand-neutral-grey-400: #C7C7C7;\n  --brand-neutral-grey-500: #BABABA;\n  --brand-neutral-grey-600: #ABABAB;\n  --brand-neutral-grey-700: #8A8A8A;\n  --brand-neutral-grey-800: #686868;\n  --brand-neutral-grey-900: #474747;\n  --brand-neutral-grey-1000: #262626;\n  --brand-blue-grey-100: #F1EFF4;\n  --brand-blue-grey-200: #E0E1E6;\n  --brand-blue-grey-300: #CFD3D8;\n  --brand-blue-grey-400: #BFC5CA;\n  --brand-blue-grey-500: #B0B5BA;\n  --brand-blue-grey-600: #A0A6AB;\n  --brand-blue-grey-700: #80898E;\n  --brand-blue-grey-800: #5E696E;\n  --brand-blue-grey-900: #404A4F;\n  --brand-blue-grey-1000: #21262B;\n  --brand-green-grey-100: #F1F4F4;\n  --brand-green-grey-200: #E0E6E6;\n  --brand-green-grey-300: #CFD8D8;\n  --brand-green-grey-400: #BFCACA;\n  --brand-green-grey-500: #B0BABA;\n  --brand-green-grey-600: #A0ABAB;\n  --brand-green-grey-700: #808E8E;\n  --brand-green-grey-800: #5E6E6E;\n  --brand-green-grey-900: #404F4F;\n  --brand-green-grey-1000: #212B2B;\n\n  /* generic fallback */\n  --font-family: var(--font-family-default);\n  --font-size: var(--body-xs-font-size);\n  --font-weight: var(--body-xs-font-weight);\n  --line-height: var(--body-xs-line-height);\n\n  /* viz */\n  --viz-series-brand: var(--bg-brand);\n  --viz-series-brand-soft: var(--brand-300);\n  --viz-series-brand-mid: var(--brand-500);\n  --viz-series-brand-deep: var(--brand-700);\n  --viz-series-neutral: var(--brand-grey-500);\n  --viz-series-coral: #F87454;\n  --viz-series-amber: #EDAA45;\n  --viz-series-mint: #1DC981;\n  --viz-series-teal: #59E8E8;\n  --viz-series-sky: #22A5F7;\n  --viz-series-violet: #B655FC;\n  --viz-series-magenta: #FB9DD7;\n  --viz-series-indigo: #B6A3FF;\n  --viz-series-lime: #A6EA39;\n  --viz-series-slate: #859EAD;\n  --viz-ui-bg-chart: var(--bg-menu);\n  --viz-ui-bg-tooltip: var(--bg-tooltip);\n  --viz-ui-chart-title: var(--text-default);\n  --viz-ui-chart-subtitle: var(--text-secondary);\n  --viz-ui-chart-axis: var(--border-neutral-l2);\n  --viz-ui-chart-tick: var(--text-secondary);\n  --viz-ui-legend-label: var(--text-secondary);\n  --viz-ui-legend-value: var(--text-default);\n\n  /* special */\n  --special-white: #FFFFFF;\n  --special-black: #000000;\n  --special-bgtabsoverlay: rgba(255, 255, 255, 0.12);\n  --special-bggoldoverlay: rgba(210, 181, 19, 0.12);\n\n  /* layout aliases */\n  --brand-1: var(--brand-600);\n  --brand-2: var(--brand-500);\n  --brand-3: var(--brand-300);\n  --brand-4: var(--brand-100);\n  --site-canvas: var(--bg-base-default);\n  --bg-layout-1: var(--bg-base-secondary);\n  --bg-layout-2: var(--bg-overlay-l1);\n  --border-1: var(--border-neutral-l1);\n\n  /* layout — app shell (theme-stable geometry tokens) */\n  --layout-sidebar: 240px;\n  --layout-sidebar-collapsed: 72px;\n  --layout-sidebar-min: 200px;\n  --layout-sidebar-max: 300px;\n  --nav-item-h: 32px;\n  --sb-foot-h: 48px;\n  --sb-item-pad-x: 10px;\n  --sb-item-gap: 8px;\n\n  /* shadow — card hover micro-elevation (registered system deviation) */\n  --shadow-card-hover: 0 2px 12px rgba(31, 33, 36, 0.08);\n}\n\n/* ═══════════════════════════════════════════════════════════════\n   Dark theme overrides\n   切换方式：在 <html> 根元素设置 data-theme="dark"（如 <html data-theme="dark">）。\n   仅覆盖语义颜色 token；radius / spacer / font / 组件 CSS 一律不变。\n   浅色为默认（不写 data-theme 即浅色），确保向后兼容旧页面。\n   ═══════════════════════════════════════════════════════════════ */\n[data-theme="dark"] {\n  /* 背景层级：画布最深，表面升一层，浮层再升（组件约定 canvas 用 --bg-base-secondary、content 用 --bg-base-default） */\n  --bg-base-default: #18181B;\n  --bg-base-secondary: #0E0E11;\n  --bg-page: #0E0E11;\n  --bg-card-hover: var(--bg-overlay-l2); /* king_2026 2026-11-06: 深色用提亮 overlay，避免 hover 变浅灰块 */\n  --bg-base-tertiary: #242428;\n  --bg-overlay-l1: rgba(255, 255, 255, 0.06);\n  --bg-overlay-l2: rgba(255, 255, 255, 0.10);\n  --bg-overlay-l3: rgba(255, 255, 255, 0.14);\n  --bg-overlay-l4: rgba(255, 255, 255, 0.18);\n  --bg-white: #1A1A1E;\n  --bg-menu: #202024;\n  --bg-tooltip: #2A2A30;\n  --bg-invert: #EDEDED;\n  --bg-invert-hover: #F5F5F5;\n  --bg-invert-active: #FFFFFF;\n  --bg-invert-disabled: rgba(255, 255, 255, 0.20);\n\n  /* 文字 */\n  --text-default: #EDEDED;\n  --text-default-hover: #FFFFFF;\n  --text-default-active: #FFFFFF;\n  --text-secondary: #A1A1A1;\n  --text-secondary-hover: #EDEDED;\n  --text-secondary-active: #EDEDED;\n  --text-tertiary: #8A8A8A;\n  --text-disabled: #5C5C62;\n\n  /* 图标（同文字语义） */\n  --icon-default: #EDEDED;\n  --icon-default-hover: #FFFFFF;\n  --icon-default-active: #FFFFFF;\n  --icon-secondary: #A1A1A1;\n  --icon-secondary-hover: #EDEDED;\n  --icon-secondary-active: #EDEDED;\n  --icon-tertiary: #8A8A8A;\n  --icon-disabled: #5C5C62;\n\n  /* 边框：白色 alpha */\n  --border-neutral-l1: rgba(255, 255, 255, 0.10);\n  --border-neutral-l2: rgba(255, 255, 255, 0.14);\n  --border-neutral-l3: rgba(255, 255, 255, 0.24);\n  --border-contrast: #FFFFFF;\n\n  /* 品牌主色：实体按钮保持；文字/图标链接提亮保对比 */\n  --bg-brand-disabled: rgba(75, 63, 227, 0.30);\n  --bg-brand-popup: rgba(170, 183, 255, 0.22);\n  --text-brand: #9D8BFF;\n  --text-brand-hover: #B6A3FF;\n  --text-brand-active: #8E80FF;\n  --icon-brand: #9D8BFF;\n  --icon-brand-hover: #B6A3FF;\n  /* 浅底品牌 tile：暗色下转深色品牌底 */\n  --brand-50: rgba(75, 63, 227, 0.18);\n  --brand-100: rgba(75, 63, 227, 0.26);\n  --brand-200: #2A2566;\n  --brand-grey-50: #1A1A1E;\n  --brand-grey-100: #202024;\n  --brand-grey-200: #2A2A30;\n\n  /* 状态色：实体色略提亮 + surface alpha 提亮（暗底可读） */\n  --status-primary-default: #4C88FF;\n  --status-primary-hover: #6BA0FF;\n  --status-primary-active: #2F6FE0;\n  --status-primary-surface-l1: rgba(76, 136, 255, 0.18);\n  --status-primary-surface-l2: rgba(76, 136, 255, 0.26);\n  --status-primary-surface-l3: rgba(76, 136, 255, 0.40);\n  --status-success-default: #2FB287;\n  --status-success-hover: #4FC59B;\n  --status-success-active: #1E8B56;\n  --status-success-surface-l1: rgba(64, 176, 139, 0.18);\n  --status-success-surface-l2: rgba(64, 176, 139, 0.26);\n  --status-success-surface-l3: rgba(64, 176, 139, 0.40);\n  --status-alert-default: #FFB700;\n  --status-alert-hover: #FFC633;\n  --status-alert-active: #E59100;\n  --status-alert-surface-l1: rgba(254, 169, 0, 0.16);\n  --status-alert-surface-l2: rgba(254, 169, 0, 0.24);\n  --status-alert-surface-l3: rgba(254, 169, 0, 0.40);\n  --status-warning-default: #F39A35;\n  --status-warning-hover: #F8B259;\n  --status-warning-active: #C46F11;\n  --status-warning-surface-l1: rgba(226, 121, 0, 0.16);\n  --status-warning-surface-l2: rgba(226, 121, 0, 0.24);\n  --status-warning-surface-l3: rgba(226, 121, 0, 0.40);\n  --status-error-default: #EA574C;\n  --status-error-hover: #F2736A;\n  --status-error-active: #C9382F;\n  --status-error-surface-l1: rgba(232, 70, 58, 0.18);\n  --status-error-surface-l2: rgba(232, 70, 58, 0.26);\n  --status-error-surface-l3: rgba(232, 70, 58, 0.40);\n\n  /* 代码配色（暗色） */\n  --code-text: #D4D4D4;\n  --code-doc: #8A94A6;\n  --code-link: #6BA0FF;\n  --code-number: #F78FB3;\n  --code-action: #C4A6FF;\n  --code-instruction: #D9A6FF;\n  --code-function: #FF9A8A;\n  --code-constant: #6CA8FF;\n  --code-parameter: #A6D957;\n  --code-attribute: #E5C07B;\n  --code-tag: #FF8A9C;\n\n  /* 图表 UI（底色随表面，其余提亮） */\n  --viz-ui-bg-chart: #1A1A1E;\n  --viz-ui-bg-tooltip: #2A2A30;\n  --viz-ui-chart-title: #EDEDED;\n  --viz-ui-chart-subtitle: #A1A1A1;\n  --viz-ui-chart-axis: rgba(255, 255, 255, 0.14);\n  --viz-ui-chart-tick: #A1A1A1;\n  --viz-ui-legend-label: #A1A1A1;\n  --viz-ui-legend-value: #EDEDED;\n  --special-bgtabsoverlay: rgba(0, 0, 0, 0.30);\n\n  /* 阴影：卡片 hover 微抬升（暗底用更深的黑影，保持"微"而非"浮起"） */\n  --shadow-card-hover: 0 2px 12px rgba(0, 0, 0, 0.45);\n}\n';

// src/designsys/components.css
var components_default = `/* ═══════════════════════════════════════════════════════════════
   components.css — Design System Component and Atom Definitions
   Component sections mirror preview/component-*.html marker blocks.
   Stable atoms live here so downstream pages do not depend on preview shell CSS.
   ═══════════════════════════════════════════════════════════════ */

/* ── Shared Atoms ───────────────────────────────────────────── */
.icon,
.icon-img {
  display: inline-block;
  color: currentColor;
  flex: 0 0 auto;
  object-fit: contain;
  vertical-align: middle;
}

.icon {
  width: var(--icon-size-16);
  height: var(--icon-size-16);
}

/* king_2026: icon mode B — currentColor 蒙版图标（契约见 library-consumption.json › iconPolicy）
   语法：<span class="icon" style="--icon-url:url({图标文件相对消费方 CSS / 页面的路径}.svg)"></span>；SVG 由消费方自带，本包不再随附图标目录（\`assets/icons/\` 已于 2026-11-03 移除）
   仅在元素显式给出 --icon-url 时生效，不影响已有内联 SVG 用法。
   颜色继承自父级的 color（须解析为 token，如 var(--text-default) / var(--text-onbrand)）。 */
.icon[style*="--icon-url"],
.icon--mask {
  background-color: currentColor;
  -webkit-mask: var(--icon-url) center / contain no-repeat;
  mask: var(--icon-url) center / contain no-repeat;
}

.icon-img {
  width: 16px;
  height: 16px;
  flex-basis: 16px;
}

.mono,
.num,
code,
kbd,
samp,
pre {
  font-family: var(--code-editor-font-family);
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1, "lnum" 1;
}

.metric-value,
.kpi-value,
.scorecard-value {
  font-family: var(--font-family-metric);
  font-variant-numeric: tabular-nums;
  font-feature-settings: "tnum" 1, "lnum" 1;
}

.ds-tooltip {
  display: inline-flex;
  align-items: center;
  gap: var(--spacer-6);
  padding: var(--spacer-6) var(--spacer-8);
  background: var(--bg-tooltip);
  color: var(--text-default);
  border: 1px solid var(--border-neutral-l2);
  border-radius: var(--radius-8);
  font-size: var(--body-sm-font-size);
  line-height: var(--body-sm-line-height);
  box-shadow: 0 12px 32px color-mix(in srgb, var(--text-default) 16%, transparent);
}

.ds-popover {
  background: var(--bg-base-default);
  border: 1px solid var(--border-neutral-l2);
  border-radius: var(--radius-12);
  padding: var(--spacer-8);
  box-shadow: 0 12px 32px color-mix(in srgb, var(--text-default) 16%, transparent);
}

.ds-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: var(--spacer-40) var(--spacer-24);
  color: var(--text-tertiary);
  text-align: center;
  border: 1px dashed var(--border-neutral-l1);
  border-radius: var(--radius-12);
}

.ds-empty__icon {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-neutral-l1);
  margin-bottom: var(--spacer-12);
  color: var(--icon-secondary);
  border-radius: var(--radius-8);
}

.ds-empty__title {
  color: var(--text-default);
  font-size: var(--body-base-font-size);
  font-weight: var(--font-weight-medium, 500);
  margin-bottom: var(--spacer-4);
}

.ds-empty__desc {
  font-size: var(--body-sm-font-size);
}

.ds-code {
  background: var(--bg-overlay-l1);
  border: 1px solid var(--border-neutral-l1);
  border-radius: var(--radius-8);
  padding: var(--spacer-12) var(--spacer-16);
  color: var(--text-default);
  font-family: var(--code-editor-font-family);
  font-size: var(--code-editor-font-size);
  line-height: var(--code-editor-line-height);
  white-space: pre;
  overflow: auto;
}

.ds-kbd {
  display: inline-flex;
  align-items: center;
  padding: 0 var(--spacer-6);
  height: 20px;
  background: transparent;
  border: 1px solid var(--border-neutral-l1);
  border-radius: var(--radius-8);
  box-shadow: none;
  font-family: var(--body-md-font-family);
  font-size: var(--body-md-font-size);
  font-weight: var(--font-weight-default, 400);
  font-variant-numeric: normal;
  font-feature-settings: normal;
  letter-spacing: var(--body-md-letter-spacing);
  color: var(--text-secondary);
}

/* ── Alert ─────────────────────────────────────────────────── */
/* ===== Notification / Toast ===== */
    .ds-notif {
      display: flex; align-items: flex-start;
      gap: var(--spacer-8);
      width: 100%; max-width: 560px;
      padding: var(--spacer-8) var(--spacer-12);
      border: 1px solid var(--border-neutral-l1);
      background: var(--bg-base-secondary);
      border-radius: var(--radius-8);
      color: var(--text-default);
      font-family: var(--body-md-font-family);
      font-size: var(--body-md-font-size);
      line-height: var(--body-md-line-height);
      letter-spacing: var(--body-md-letter-spacing);
      box-shadow: none;
    }
    .ds-notif__icon { flex: 0 0 16px; width: 16px; height: 16px; margin-top: var(--spacer-2); color: var(--icon-default); display: inline-flex; align-items: center; justify-content: center; }
    .ds-notif__body { flex: 1; min-width: 0; }
    .ds-notif__title { font-family: var(--body-md-strong-font-family); font-size: var(--body-md-strong-font-size); line-height: var(--body-md-strong-line-height); font-weight: var(--body-md-strong-font-weight); letter-spacing: var(--body-md-strong-letter-spacing); color: var(--text-default); }
    .ds-notif__text { flex: 1; color: var(--text-default); }
    .ds-notif__desc { margin-top: var(--spacer-2); color: var(--text-secondary); font-size: var(--body-md-font-size); line-height: var(--body-md-line-height); }
    .ds-notif__actions { display: inline-flex; align-items: center; gap: var(--spacer-8); margin-top: var(--spacer-8); }
    .ds-notif__close { flex-shrink: 0; width: 24px; height: 24px; display: inline-flex; align-items: center; justify-content: center; background: transparent; border: none; cursor: pointer; color: var(--icon-secondary); border-radius: var(--radius-8); }
    .ds-notif__close .icon { width: 14px; height: 14px; }
    .ds-notif__close:hover { background: var(--bg-overlay-l2); color: var(--icon-default); }
    .ds-notif--simple { align-items: center; }
    .ds-notif--error { background: var(--status-error-surface-l1); border-color: var(--status-error-surface-l2); }
    .ds-notif--error .ds-notif__icon { color: var(--status-error-default); }
    .ds-notif--warning { background: var(--status-warning-surface-l1); border-color: var(--status-warning-surface-l2); }
    .ds-notif--warning .ds-notif__icon { color: var(--status-warning-default); }
    .ds-notif--alert { background: var(--status-alert-surface-l1); border-color: var(--status-alert-surface-l2); }
    .ds-notif--alert .ds-notif__icon { color: var(--status-alert-default); }
    .ds-notif--info { background: var(--status-primary-surface-l1); border-color: var(--status-primary-surface-l2); }
    .ds-notif--info .ds-notif__icon { color: var(--status-primary-default); }
    .ds-notif--success { background: var(--status-success-surface-l1); border-color: var(--status-success-surface-l2); }
    .ds-notif--success .ds-notif__icon { color: var(--status-success-default); }

    /* ===== Alert / Banner ===== */
    .ds-alert {
      display: flex; align-items: flex-start;
      gap: var(--spacer-12);
      padding: var(--spacer-12) var(--spacer-16);
      background: var(--bg-base-secondary);
      border: 1px solid var(--border-neutral-l1);
      border-radius: var(--radius-8);
      color: var(--text-default);
      font-family: var(--body-md-font-family);
      font-size: var(--body-md-font-size);
      line-height: var(--body-md-line-height);
      letter-spacing: var(--body-md-letter-spacing);
    }
    .ds-alert__icon { flex: 0 0 16px; width: 16px; height: 16px; margin-top: var(--spacer-2); color: var(--icon-default); display: inline-flex; align-items: center; justify-content: center; }
    .ds-notif__icon .icon, .ds-alert__icon .icon { width: 16px; height: 16px; display: block; }
    .ds-alert--success .ds-alert__icon { color: var(--status-success-default); }
    .ds-alert--warning .ds-alert__icon { color: var(--status-warning-default); }
    .ds-alert--danger .ds-alert__icon { color: var(--status-error-default); }
    .ds-alert--info .ds-alert__icon { color: var(--status-primary-default); }
    .ds-alert__title { font-family: var(--body-md-strong-font-family); font-size: var(--body-md-strong-font-size); line-height: var(--body-md-strong-line-height); font-weight: var(--body-md-strong-font-weight); letter-spacing: var(--body-md-strong-letter-spacing); margin-bottom: var(--spacer-4); }
    .ds-alert__desc { color: var(--text-secondary); font-size: var(--body-md-font-size); line-height: var(--body-md-line-height); }

/* ── Avatar ────────────────────────────────────────────────── */
/* ===== Avatar ===== */
    .ds-avatar {
      display: inline-flex; align-items: center; justify-content: center;
      width: 32px; height: 32px; border-radius: 999px;
      background: var(--bg-overlay-l3);
      color: var(--text-default);
      font-family: var(--body-base-strong-font-family);
      font-size: var(--body-base-strong-font-size);
      font-weight: var(--body-base-strong-font-weight);
      line-height: var(--body-base-strong-line-height);
      flex-shrink: 0;
    }
    .ds-avatar--sm { width: 24px; height: 24px; font-size: var(--body-sm-font-size); }
    .ds-avatar--lg { width: 40px; height: 40px; }

/* ── Breadcrumb ────────────────────────────────────────────── */
/* ===== Breadcrumb ===== */
    .ds-breadcrumb { display: flex; align-items: center; gap: var(--spacer-8); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); color: var(--text-tertiary); }
    .ds-breadcrumb a { display: inline-flex; align-items: center; color: var(--text-tertiary); }
    .ds-breadcrumb a:hover { color: var(--text-brand); }
    .ds-breadcrumb__sep { color: var(--text-tertiary); }
    .ds-breadcrumb__current { color: var(--text-brand); }

/* ── Buttons ───────────────────────────────────────────────── */
/* ===== Buttons ===== */
    .ds-btn {
      display: inline-flex; align-items: center; justify-content: center;
      gap: var(--spacer-6);
      height: 28px; padding: 0 var(--spacer-12);
      border-radius: var(--radius-8);
      border: 1px solid transparent;
      cursor: pointer; user-select: none; white-space: nowrap;
      font-family: var(--body-base-strong-font-family);
      font-size: var(--body-base-strong-font-size);
      line-height: var(--body-base-strong-line-height);
      font-weight: var(--body-base-strong-font-weight);
      letter-spacing: var(--body-base-strong-letter-spacing);
      transition: background .12s ease, color .12s ease, border-color .12s ease, opacity .12s ease;
    }
    .ds-btn .icon {
      display: inline-block;
      width: var(--icon-size-16);
      height: var(--icon-size-16);
      flex: 0 0 auto;
    }
    .ds-btn .icon--12 { width: var(--icon-size-12); height: var(--icon-size-12); }
    .ds-btn .icon--14 { width: var(--icon-size-14); height: var(--icon-size-14); }
    .ds-btn .icon--16 { width: var(--icon-size-16); height: var(--icon-size-16); }
    .ds-btn .icon--20 { width: var(--icon-size-20); height: var(--icon-size-20); }
    .ds-btn .icon--24 { width: var(--icon-size-24); height: var(--icon-size-24); }
    /* Button heights are fixed to 24 / 28 / 32px. */
    .ds-btn--sm { height: 24px; padding: 0 var(--spacer-8); border-radius: var(--radius-8); font-size: var(--body-sm-font-size); }
    .ds-btn--md { height: 28px; padding: 0 var(--spacer-12); border-radius: var(--radius-8); }
    .ds-btn--lg { height: 32px; padding: 0 var(--spacer-16); border-radius: var(--radius-8); font-size: var(--body-base-font-size); }
    .ds-btn--primary { background: var(--bg-brand); color: var(--text-onbrand); border-color: var(--bg-brand); }
    .ds-btn--primary:hover { background: var(--bg-brand-hover); border-color: var(--bg-brand-hover); }
    .ds-btn--primary:active { background: var(--bg-brand-active); border-color: var(--bg-brand-active); }
    .ds-btn--primary[disabled] { background: var(--bg-brand-disabled); color: var(--text-onbrand); border-color: transparent; cursor: not-allowed; }
    .ds-btn--secondary { background: var(--bg-overlay-l1); color: var(--text-default); border-color: var(--border-neutral-l1); }
    .ds-btn--secondary:hover { background: var(--bg-overlay-l2); border-color: var(--border-neutral-l2); }
    .ds-btn--secondary:active { background: var(--bg-overlay-l3); border-color: var(--border-neutral-l3); }
    .ds-btn--secondary[disabled] { color: var(--text-disabled); cursor: not-allowed; opacity: .7; }
    .ds-btn--tertiary,
    .ds-btn--ghost { background: transparent; color: var(--text-default); border-color: transparent; }
    .ds-btn--tertiary:hover,
    .ds-btn--ghost:hover { background: var(--bg-overlay-l2); color: var(--text-default-hover); }
    .ds-btn--tertiary:active,
    .ds-btn--ghost:active { background: var(--bg-overlay-l3); }
    .ds-btn--tertiary[disabled],
    .ds-btn--ghost[disabled] { color: var(--text-disabled); cursor: not-allowed; }
    .ds-btn--danger,
    .ds-btn--danger-strong { background: var(--status-error-default); color: var(--text-onaccent); border-color: var(--status-error-default); }
    .ds-btn--danger:hover,
    .ds-btn--danger-strong:hover { background: var(--status-error-hover); border-color: var(--status-error-hover); }
    .ds-btn--danger:active,
    .ds-btn--danger-strong:active { background: var(--status-error-active); border-color: var(--status-error-active); }
    .ds-btn--danger-subtle { background: var(--status-error-surface-l1); color: var(--status-error-default); border-color: var(--status-error-surface-l2); }
    .ds-btn--danger-subtle:hover { background: var(--status-error-surface-l2); }
    .ds-btn--danger-subtle:active { background: var(--status-error-surface-l3); }
    .ds-btn--warning { background: var(--status-warning-default); color: var(--text-onaccent); border-color: var(--status-warning-default); }
    .ds-btn--warning:hover { background: var(--status-warning-hover); border-color: var(--status-warning-hover); }
    .ds-btn--warning:active { background: var(--status-warning-active); border-color: var(--status-warning-active); }
    .ds-btn--link { background: transparent; color: var(--text-brand); border-color: transparent; padding: 0; height: auto; }
    .ds-btn--link:hover { color: var(--text-brand-hover); text-decoration: none; }
    .ds-btn--link:active { color: var(--text-brand-active); }
    .ds-btn--link[disabled] { color: var(--text-disabled); text-decoration: none; cursor: not-allowed; }
    .ds-btn--icon { width: 28px; padding: 0; justify-content: center; }
    .ds-btn--icon.ds-btn--sm { width: 24px; }
    .ds-btn--icon.ds-btn--lg { width: 32px; }
    .ds-btn-group { display: inline-flex; }
    .ds-btn-group > .ds-btn { border-radius: 0; margin-left: calc(-1 * var(--border-width-default)); }
    .ds-btn-group > .ds-btn:first-child { border-top-left-radius: var(--radius-8); border-bottom-left-radius: var(--radius-8); margin-left: 0; }
    .ds-btn-group > .ds-btn:last-child { border-top-right-radius: var(--radius-8); border-bottom-right-radius: var(--radius-8); }

/* ── Cards ─────────────────────────────────────────────────── */
/* ===== Card ===== */
    .ds-card {
      background: var(--bg-base-default);
      border: 1px solid var(--border-neutral-l1);
      border-radius: var(--radius-12);
      padding: var(--spacer-20);
      color: var(--text-default);
      transition: background-color .15s ease;
    }
    .ds-card:hover { background: var(--bg-card-hover); } /* king_2026 2026-11-06 修订: 卡片带 1px 中性描边且恒定不变，hover 只置灰（#F6F6F6），不加投影 */
    .ds-card__title { font-size: var(--heading-sm-font-size); line-height: var(--heading-sm-line-height); font-weight: var(--heading-sm-font-weight); margin-bottom: var(--spacer-8); }
    .ds-card__desc { font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); color: var(--text-secondary); }

/* ── Dialog ────────────────────────────────────────────────── */
/* ===== Dialog / Modal ===== */
    .ds-backdrop { position: relative; background: var(--bg-overlay-l4); border: 1px solid var(--border-neutral-l1); padding: var(--spacer-32) var(--spacer-24); display: flex; align-items: center; justify-content: center; }
    .ds-dialog { background: var(--bg-base-default); border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-12); width: 100%; max-width: 520px; overflow: hidden; color: var(--text-default); box-shadow: 0 24px 64px color-mix(in srgb, var(--text-default) 14%, transparent), 0 4px 16px color-mix(in srgb, var(--text-default) 8%, transparent); }
    .ds-dialog--form { max-width: 560px; }
    .ds-dialog__head { padding: var(--spacer-16) var(--spacer-20); display: flex; align-items: center; justify-content: space-between; border-bottom: 0; }
    .ds-dialog__title { font-size: var(--heading-sm-font-size); line-height: var(--heading-sm-line-height); font-weight: var(--heading-sm-font-weight); color: var(--text-default); }
    .ds-dialog__close { width: 32px; height: 32px; display: inline-flex; align-items: center; justify-content: center; background: transparent; border: none; color: var(--icon-secondary); cursor: pointer; border-radius: var(--radius-8); }
    .ds-dialog__close:hover { background: var(--bg-overlay-l2); color: var(--icon-default); }
    .ds-dialog__body { padding: var(--spacer-16) var(--spacer-20); color: var(--text-secondary); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); }
    .ds-dialog__foot { padding: var(--spacer-12) var(--spacer-20); display: flex; justify-content: flex-end; gap: var(--spacer-8); border-top: 0; }
    .ds-drawer { background: var(--bg-base-default); border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-12); width: 100%; max-width: 360px; display: flex; flex-direction: column; box-shadow: 0 24px 64px color-mix(in srgb, var(--text-default) 14%, transparent), 0 4px 16px color-mix(in srgb, var(--text-default) 8%, transparent); }
    .ds-drawer__head { padding: var(--spacer-16) var(--spacer-20); display: flex; justify-content: space-between; align-items: center; border-bottom: 0; }
    .ds-drawer__body { padding: var(--spacer-16) var(--spacer-20); flex: 1; }
    .dialog-form { display: grid; gap: var(--spacer-16); }
    .dialog-field { display: flex; flex-direction: column; gap: var(--spacer-6); }
    .dialog-field__label { color: var(--text-default); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); font-weight: var(--font-weight-medium); }
    .dialog-field__hint { color: var(--text-tertiary); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); }
    .dialog-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--spacer-12); }
    .dialog-form .ds-input,
    .dialog-form .ds-select,
    .dialog-form .ds-textarea { background: var(--bg-base-default); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); letter-spacing: var(--body-base-letter-spacing); }
    .dialog-form .ds-input:focus-within,
    .dialog-form .ds-select:focus,
    .dialog-form .ds-textarea:focus { background: var(--bg-base-default); }
    .dialog-form .ds-textarea { min-height: 72px; resize: none; }
    .dialog-calendar-icon { width: 16px; height: 16px; color: var(--icon-secondary); object-fit: contain; }
    @media (max-width: 720px) { .dialog-grid { grid-template-columns: 1fr; } }

/* ── Forms ─────────────────────────────────────────────────── */
/* ===== Input / Search ===== */
    .ds-input { display: flex; align-items: center; gap: var(--spacer-8); min-height: 32px; padding: 0 var(--spacer-12); background: var(--bg-base-default); border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-8); color: var(--text-default); width: 100%; font-family: var(--body-base-font-family); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); }
    .ds-input:focus-within { border-color: var(--border-contrast); background: var(--bg-base-default); }
    .ds-input input { flex: 1; background: transparent; border: none; outline: none; color: var(--text-default); font: inherit; min-width: 0; }
    .ds-input input[type="number"] { appearance: textfield; -moz-appearance: textfield; }
    .ds-input input[type="number"]::-webkit-outer-spin-button,
    .ds-input input[type="number"]::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
    .ds-input input::placeholder { color: var(--text-tertiary); }
    .ds-input input:disabled { color: var(--text-disabled); cursor: not-allowed; }
    .ds-input.is-error { border-color: var(--status-error-default); }
    .ds-input.is-disabled { background: var(--bg-base-secondary); color: var(--text-disabled); cursor: not-allowed; }
    .ds-input__icon { color: var(--icon-secondary); display: inline-flex; align-items: center; }
    .ds-search { position: relative; }
    .ds-select { width: 100%; height: 32px; padding: 0 var(--spacer-32) 0 var(--spacer-12); background-color: var(--bg-base-default); color: var(--text-default); border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-8); appearance: none; -webkit-appearance: none; font: inherit; font-size: var(--body-base-font-size); }
    .ds-select:focus { border-color: var(--border-contrast); background-color: var(--bg-base-default); outline: none; }
    .ds-select:disabled { background-color: var(--bg-base-secondary); color: var(--text-disabled); cursor: not-allowed; opacity: 1; }
    .ds-select-wrap { position: relative; width: 100%; }
    .ds-select-wrap .ds-select { padding-right: var(--spacer-32); }
    .ds-select__icon { position: absolute; right: var(--spacer-12); top: 50%; width: 16px; height: 16px; color: var(--icon-secondary); pointer-events: none; transform: translateY(-50%); object-fit: contain; }
    .ds-select-wrap > .icon-img { position: absolute; top: 50%; right: var(--spacer-10); transform: translateY(-50%); color: var(--icon-secondary); pointer-events: none; }
    .icon-img { display: inline-block; width: 16px; height: 16px; flex: 0 0 16px; object-fit: contain; vertical-align: middle; }
    .icon-img--12 { width: 12px; height: 12px; flex-basis: 12px; }
    .icon-img--14 { width: 14px; height: 14px; flex-basis: 14px; }
    .ds-textarea { width: 100%; min-height: 96px; padding: var(--spacer-8) var(--spacer-12); background: var(--bg-base-default); border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-8); color: var(--text-default); font-family: var(--body-base-font-family); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); resize: none; }
    .ds-textarea:focus { outline: none; border-color: var(--border-contrast); background: var(--bg-base-default); }
    .ds-textarea.is-error { border-color: var(--status-error-default); }
    .ds-slider { -webkit-appearance: none; appearance: none; width: 100%; height: 4px; background: var(--bg-overlay-l3); border-radius: 999px; outline: none; }
    .ds-slider--progress { background: var(--bg-overlay-l3); }
    .ds-slider::-webkit-slider-thumb { -webkit-appearance: none; width: 14px; height: 14px; border-radius: 999px; background: var(--bg-base-default); border: 1px solid var(--border-neutral-l3); box-shadow: none; cursor: pointer; }
    .ds-slider::-moz-range-track { height: 4px; background: var(--bg-overlay-l3); border-radius: 999px; }
    .ds-slider--progress::-moz-range-progress { height: 4px; background: var(--bg-brand); border-radius: 999px; }
    .ds-slider::-moz-range-thumb { width: 14px; height: 14px; border-radius: 999px; background: var(--bg-base-default); border: 1px solid var(--border-neutral-l3); box-shadow: none; cursor: pointer; }
    .ds-check, .ds-radio { display: inline-flex; align-items: center; gap: var(--spacer-8); min-height: 40px; font-size: var(--body-base-font-size); color: var(--text-default); cursor: pointer; user-select: none; }
    .ds-check__box { width: 16px; height: 16px; border: 1px solid var(--border-neutral-l2); background: var(--bg-base-default); border-radius: var(--radius-4); display: inline-flex; align-items: center; justify-content: center; color: var(--text-onbrand); transition: background .12s, border-color .12s; }
    .ds-check input { display: none; }
    .ds-check input:checked + .ds-check__box { background: var(--bg-brand); border-color: var(--bg-brand); }
    .ds-check input:checked + .ds-check__box::after { content: ''; width: 8px; height: 4px; border-left: 2px solid var(--text-onbrand); border-bottom: 2px solid var(--text-onbrand); transform: rotate(-45deg) translate(1px, -1px); }
    .ds-check input:disabled + .ds-check__box { opacity: .5; cursor: not-allowed; }
    .ds-radio__dot { width: 16px; height: 16px; border: 1px solid var(--border-neutral-l2); background: var(--bg-base-default); border-radius: 999px; display: inline-flex; align-items: center; justify-content: center; }
    .ds-radio input { display: none; }
    .ds-radio input:checked + .ds-radio__dot { border-color: var(--bg-brand); }
    .ds-radio input:checked + .ds-radio__dot::after { content: ''; width: 10px; height: 10px; border-radius: 999px; background: var(--bg-brand); }
    .ds-switch { position: relative; display: inline-flex; width: 32px; height: 18px; background: var(--bg-overlay-l3); border: 1px solid var(--border-neutral-l1); border-radius: 999px; cursor: pointer; transition: background .15s, border-color .15s; }
    .ds-switch input { display: none; }
    .ds-switch__thumb { position: absolute; top: 2px; left: 2px; width: 12px; height: 12px; background: var(--bg-base-default); border-radius: 999px; transition: left .15s, background .15s; }
    .ds-switch input:checked ~ .ds-switch__thumb { left: 16px; background: var(--icon-onbrand); }
    .ds-switch:has(input:checked) { background: var(--bg-brand); border-color: var(--bg-brand); }
    .input-affix { color: var(--text-tertiary); font-family: var(--body-base-font-family); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); white-space: nowrap; }
    .ds-date-input { position: relative; }
    .ds-date-input input { padding-right: var(--spacer-32); }
    .ds-date-input input::-webkit-calendar-picker-indicator { opacity: 0; cursor: pointer; }
    .ds-date-input .icon-img { position: absolute; top: 50%; right: var(--spacer-12); transform: translateY(-50%); color: var(--icon-secondary); pointer-events: none; }
    .tag-field { display: flex; align-items: center; flex-wrap: wrap; gap: var(--spacer-6); min-height: 32px; padding: var(--spacer-4) var(--spacer-8); border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-8); background: var(--bg-base-default); }
    .tag-field:focus-within { border-color: var(--border-contrast); }
    .tag-remove { display: inline-flex; align-items: center; justify-content: center; width: 16px; height: 16px; padding: 0; border: 0; background: transparent; color: var(--icon-tertiary); cursor: pointer; border-radius: var(--radius-4); }
    .tag-remove:hover { background: var(--bg-overlay-l2); color: var(--icon-default); }
    .stepper { display: inline-flex; align-items: center; width: fit-content; border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-8); overflow: hidden; background: var(--bg-base-default); }
    .stepper button { display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px; border: 0; background: transparent; color: var(--icon-secondary); cursor: pointer; }
    .stepper button:hover { background: var(--bg-overlay-l2); color: var(--icon-default); }
    .stepper input { width: 48px; height: 32px; padding: 0; border: 0; border-left: 1px solid var(--border-neutral-l1); border-right: 1px solid var(--border-neutral-l1); background: transparent; color: var(--text-default); text-align: center; font: inherit; line-height: var(--body-base-line-height); appearance: textfield; -moz-appearance: textfield; }
    .stepper input::-webkit-outer-spin-button,
    .stepper input::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }

/* ── Menu ──────────────────────────────────────────────────── */
/* ===== Menu ===== */
    .ds-menu { display: flex; flex-direction: column; gap: var(--spacer-2); background: var(--bg-menu); border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-12); padding: var(--spacer-8); min-width: 180px; color: var(--text-default); box-shadow: 0 12px 32px color-mix(in srgb, var(--text-default) 12%, transparent), 0 2px 8px color-mix(in srgb, var(--text-default) 8%, transparent); }
    .ds-menu__item { display: flex; align-items: center; gap: var(--spacer-8); min-height: 32px; padding: var(--spacer-6) var(--spacer-8); border-radius: var(--radius-8); color: var(--text-default); font-family: var(--body-base-font-family); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); font-weight: var(--body-base-font-weight); cursor: pointer; }
    .ds-menu__item .icon { color: var(--icon-secondary); }
    .ds-menu__icon { width: 16px; height: 16px; flex: 0 0 auto; object-fit: contain; }
    .ds-menu__item:hover { background: var(--bg-overlay-l2); }
    .ds-menu__item--danger { color: var(--status-error-default); }
    .ds-menu__item--danger .icon,
    .ds-menu__item--danger .ds-menu__icon { color: var(--status-error-default); }
    .ds-menu__divider { height: 1px; background: var(--border-neutral-l1); margin: var(--spacer-4) 0; }
    .ds-menu__shortcut { margin-left: auto; color: var(--text-tertiary); font-family: var(--body-md-font-family); font-size: var(--body-md-font-size); line-height: var(--body-md-line-height); font-weight: var(--body-md-font-weight); font-variant-numeric: normal; font-feature-settings: normal; }
    .ds-menu__group-label { padding: var(--spacer-8); color: var(--text-tertiary); font-family: var(--body-md-font-family); font-size: var(--body-md-font-size); line-height: var(--body-md-line-height); font-weight: var(--body-md-font-weight); letter-spacing: var(--body-md-letter-spacing); text-transform: uppercase; }
    .ds-popover .ds-menu { border: 0; padding: 0; box-shadow: none; }

/* ── Pagination ────────────────────────────────────────────── */
/* ===== Pagination ===== */
    .ds-pagination { display: inline-flex; gap: var(--spacer-4); }
    .ds-pagination__item { min-width: 32px; height: 32px; padding: 0 var(--spacer-8); display: inline-flex; align-items: center; justify-content: center; background: transparent; color: var(--text-secondary); border: 1px solid var(--border-neutral-l1); border-radius: var(--radius-8); font: inherit; font-size: var(--body-base-font-size); cursor: pointer; }
    .ds-pagination__item:hover { background: var(--bg-overlay-l2); color: var(--text-default); }
    .ds-pagination__item.is-active { background: var(--bg-brand); color: var(--text-onbrand); border-color: var(--bg-brand); }
    .ds-pagination__item[disabled] { opacity: .4; cursor: not-allowed; }
    .ds-pagination__range { color: var(--text-tertiary); font-family: var(--body-sm-font-family); font-size: var(--body-sm-font-size); line-height: var(--body-sm-line-height); font-weight: var(--body-sm-font-weight); letter-spacing: var(--body-sm-letter-spacing); }

/* ── Progress ──────────────────────────────────────────────── */
/* ===== Progress ===== */
    .ds-progress { height: 6px; background: var(--bg-overlay-l2); border-radius: 999px; overflow: hidden; }
    .ds-progress__bar { height: 100%; background: var(--bg-brand); border-radius: inherit; } /* king_2026: 进度条填充统一主题色，见 design-system-overview 规约 */

/* ── Skeleton ──────────────────────────────────────────────── */
/* ===== Skeleton ===== */
    .ds-skeleton { display: block; background: var(--bg-overlay-l2); border-radius: var(--radius-8); position: relative; overflow: hidden; }
    .ds-skeleton::after { content: ''; position: absolute; inset: 0; background: linear-gradient(90deg, transparent, var(--bg-overlay-l3), transparent); animation: ds-skeleton-shine 1.6s ease-in-out infinite; }
    @keyframes ds-skeleton-shine { 0% { transform: translateX(-100%); } 100% { transform: translateX(100%); } }
    .ds-skeleton--line { height: 12px; }
    .ds-skeleton--title { height: 18px; width: 50%; }
    .ds-skeleton--circle { width: 32px; height: 32px; border-radius: 999px; }

/* ── Table ─────────────────────────────────────────────────── */
/* ===== Table ===== */
    .ds-table-card { overflow-x: auto; }
    .ds-table { width: 100%; min-width: 720px; border-collapse: collapse; }
    .ds-table--fixed { table-layout: fixed; }
    .ds-table__col-member { width: 42%; }
    .ds-table__col-role { width: 16%; }
    .ds-table__col-active { width: 20%; }
    .ds-table__col-status { width: 16%; }
    .ds-table__col-actions { width: 6%; }
    .ds-table th, .ds-table td { text-align: left; vertical-align: middle; padding: var(--spacer-16) var(--spacer-8); border-bottom: 1px solid var(--border-neutral-l1); font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); }
    .ds-table th { padding-top: var(--spacer-8); padding-bottom: var(--spacer-12); color: var(--text-tertiary); font-weight: var(--font-weight-medium); font-size: var(--body-md-font-size); line-height: var(--body-md-line-height); text-transform: uppercase; letter-spacing: var(--body-md-letter-spacing); background: transparent; }
    .ds-table td { color: var(--text-secondary); }
    .ds-table td:first-child { color: var(--text-default); }
    .ds-table tr:last-child td { border-bottom: none; }
    .ds-table td.num,
    .ds-table th.num { text-align: right; font-family: var(--code-editor-font-family); font-variant-numeric: tabular-nums; }
    .ds-table__member { display: flex; align-items: center; gap: var(--spacer-16); min-width: 0; }
    .ds-table__member-meta { display: flex; flex-direction: column; gap: var(--spacer-2); min-width: 0; }
    .ds-table__member-name { color: var(--text-default); font-weight: var(--font-weight-medium); white-space: nowrap; }
    .ds-table__member-email { color: var(--text-tertiary); font-size: var(--body-md-font-size); line-height: var(--body-md-line-height); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .ds-table td.ds-table__actions { width: 1%; text-align: right; }

/* ── Tabs ──────────────────────────────────────────────────── */
/* ===== Tabs ===== */
    .ds-tabs { display: flex; gap: var(--spacer-24); border-bottom: 1px solid var(--border-neutral-l1); }
    .ds-tab { display: inline-flex; align-items: center; padding: var(--spacer-12) 0; background: transparent; border: none; color: var(--text-tertiary); cursor: pointer; font: inherit; font-size: var(--body-base-font-size); line-height: var(--body-base-line-height); font-weight: var(--font-weight-medium); position: relative; }
    .ds-tab:hover { color: var(--text-brand); }
    .ds-tab.is-active { color: var(--text-brand); }
    .ds-tab.is-active::after { content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 2px; background: var(--bg-brand); }
    .ds-tab__count,
    .ds-tab .ds-tag.num { margin-left: var(--spacer-6); min-width: 18px; height: 18px; padding: 0 var(--spacer-6); display: inline-grid; place-items: center; vertical-align: middle; border: none; border-radius: 999px; background: var(--bg-overlay-l2); color: var(--text-tertiary); font-family: var(--font-family-metric); font-size: var(--body-xs-font-size); line-height: var(--body-xs-line-height); font-weight: var(--body-xs-font-weight); font-variant-numeric: tabular-nums; }

/* ── Tag ───────────────────────────────────────────────────── */
/* ===== Tag / Badge ===== */
    .ds-tag { display: inline-flex; align-items: center; gap: var(--spacer-4); height: 22px; padding: 0 var(--spacer-8); border-radius: var(--radius-8); font-size: var(--body-sm-font-size); line-height: var(--body-sm-line-height); background: var(--bg-overlay-l2); color: var(--text-secondary); border: 1px solid var(--border-neutral-l1); }
    .ds-tag .icon { width: 12px; height: 12px; }
    .ds-tag--brand { background: var(--bg-brand-popup); color: var(--text-brand); }
    .ds-tag--success { background: var(--status-success-surface-l1); color: var(--status-success-default); }
    .ds-tag--warning { background: var(--status-warning-surface-l1); color: var(--status-warning-default); }
    .ds-tag--danger { background: var(--status-error-surface-l1); color: var(--status-error-default); }
`;

// src/styles.css
var styles_default = '/**\n * Page-local layout, on top of the design system\'s atoms.\n *\n * Nothing here names a colour: every value is a semantic token from\n * `designsys/colors_and_type.css`, which carries both themes.  A rule that\n * needed a colour the tokens do not offer would be a signal that the rule is\n * wrong, not that a literal is missing.\n *\n * The one deviation from `.ds-card` is deliberate: `.ds-card` lights up on\n * hover, which is right for a card you can click and wrong for a panel you\n * read.  Static surfaces therefore use `.pbe-panel`, and interactive ones add\n * `.pbe-panel--link`.\n */\n\n/* ── shell ─────────────────────────────────────────────────────────────── */\n\n.pbe-root {\n  display: block;\n  min-height: 100%;\n  background: var(--bg-base-secondary);\n  color: var(--text-default);\n  font-family: var(--body-base-font-family);\n  font-size: var(--body-base-font-size);\n  line-height: var(--body-base-line-height);\n  -webkit-font-smoothing: antialiased;\n}\n\n/*\n * The rail and the module sit in one row that this file owns.\n *\n * Deliberately not expressed on `.pbe-root`: between the two there is antd\'s\n * `App` wrapper, whose display is the host build\'s business.  Relying on it\n * being a pass-through produced a page whose content started 100vh down the\n * screen — one row for the rail, another for everything else.\n */\n.pbe-shell {\n  display: flex;\n  flex-wrap: nowrap;\n  align-items: flex-start;\n  min-height: 100%;\n}\n\n.pbe-rail {\n  position: sticky;\n  top: 0;\n  display: flex;\n  flex: 0 0 var(--layout-sidebar);\n  flex-direction: column;\n  gap: var(--spacer-16);\n  width: var(--layout-sidebar);\n  height: 100vh;\n  padding: var(--spacer-16) var(--spacer-12);\n  border-right: 1px solid var(--border-neutral-l1);\n  background: var(--bg-menu);\n  box-sizing: border-box;\n}\n\n.pbe-rail__brand {\n  display: flex;\n  align-items: center;\n  gap: var(--spacer-8);\n  padding: 0 var(--spacer-8);\n  color: var(--text-default);\n  font-family: var(--font-family-heading);\n  font-size: var(--body-lg-font-size);\n  font-weight: 600;\n}\n\n.pbe-rail__nav {\n  display: flex;\n  flex-direction: column;\n  gap: 2px;\n}\n\n.pbe-nav-item {\n  display: flex;\n  align-items: center;\n  gap: var(--sb-item-gap);\n  width: 100%;\n  height: var(--nav-item-h);\n  padding: 0 var(--sb-item-pad-x);\n  border: 0;\n  border-radius: var(--radius-8);\n  background: transparent;\n  color: var(--text-default);\n  font-family: inherit;\n  font-size: var(--body-base-font-size);\n  text-align: left;\n  cursor: pointer;\n}\n\n.pbe-nav-item:hover {\n  background: var(--bg-overlay-l1);\n}\n\n.pbe-nav-item[aria-current="page"] {\n  background: var(--bg-overlay-l2);\n  font-weight: 500;\n}\n\n.pbe-nav-item__count {\n  margin-left: auto;\n  color: var(--text-tertiary);\n  font-family: var(--code-editor-font-family);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-rail__foot {\n  margin-top: auto;\n  padding: var(--spacer-12);\n  border: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-12);\n  background: var(--bg-base-default);\n  text-align: left;\n  cursor: pointer;\n  font: inherit;\n  color: inherit;\n  width: 100%;\n}\n\n.pbe-rail__foot:hover {\n  background: var(--bg-card-hover);\n}\n\n.pbe-main {\n  flex: 1 1 auto;\n  min-width: 0;\n  padding: var(--spacer-24) var(--spacer-32) var(--spacer-32);\n}\n\n/* ── page heading ──────────────────────────────────────────────────────── */\n\n.pbe-head {\n  display: flex;\n  align-items: flex-start;\n  gap: var(--spacer-16);\n  margin-bottom: var(--spacer-24);\n  /* The host parks a floating control (… and collapse) in the top-right corner\n     of every route; without this the primary button sits under it. */\n  padding-right: 76px;\n}\n\n.pbe-head__text {\n  min-width: 0;\n}\n\n.pbe-head__title {\n  margin: 0;\n  color: var(--text-default);\n  font-family: var(--font-family-heading);\n  font-size: var(--heading-lg-font-size);\n  font-weight: 600;\n  line-height: var(--heading-lg-line-height);\n}\n\n.pbe-head__sub {\n  margin-top: var(--spacer-4);\n  color: var(--text-secondary);\n  font-size: var(--body-base-font-size);\n}\n\n.pbe-head__actions {\n  display: flex;\n  align-items: center;\n  gap: var(--spacer-8);\n  margin-left: auto;\n}\n\n/* ── surfaces ──────────────────────────────────────────────────────────── */\n\n.pbe-panel {\n  background: var(--bg-base-default);\n  border: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-12);\n}\n\n.pbe-panel--pad {\n  padding: var(--spacer-20);\n}\n\n.pbe-panel--link {\n  cursor: pointer;\n  transition: background-color 0.15s ease;\n}\n\n.pbe-panel--link:hover {\n  background: var(--bg-card-hover);\n}\n\n.pbe-grid {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: var(--spacer-16);\n  align-items: start;\n}\n\n.pbe-grid--wide {\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n}\n\n@media (max-width: 1000px) {\n  .pbe-grid,\n  .pbe-grid--wide {\n    grid-template-columns: minmax(0, 1fr);\n  }\n}\n\n.pbe-span-all {\n  grid-column: 1 / -1;\n}\n\n/* ── metric row (C2 tier) ──────────────────────────────────────────────── */\n\n.pbe-metrics {\n  display: grid;\n  grid-template-columns: repeat(3, minmax(0, 1fr));\n  gap: var(--spacer-16);\n  margin-bottom: var(--spacer-24);\n}\n\n@media (max-width: 1000px) {\n  .pbe-metrics {\n    grid-template-columns: repeat(2, minmax(0, 1fr));\n  }\n}\n\n@media (max-width: 680px) {\n  .pbe-metrics {\n    grid-template-columns: minmax(0, 1fr);\n  }\n}\n\n.pbe-metric {\n  display: flex;\n  align-items: center;\n  gap: var(--spacer-12);\n  height: 72px;\n  padding: var(--spacer-16);\n  box-sizing: border-box;\n}\n\n.pbe-tile {\n  display: inline-flex;\n  flex: 0 0 44px;\n  align-items: center;\n  justify-content: center;\n  width: 44px;\n  height: 44px;\n  border: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-8);\n  background: transparent;\n  color: var(--text-secondary);\n}\n\n.pbe-metric__body {\n  min-width: 0;\n}\n\n.pbe-metric__title {\n  color: var(--text-default);\n  font-size: var(--body-base-font-size);\n  font-weight: 600;\n  line-height: 20px;\n  white-space: nowrap;\n  overflow: hidden;\n  text-overflow: ellipsis;\n}\n\n.pbe-metric__desc {\n  display: flex;\n  align-items: center;\n  gap: var(--spacer-6);\n  height: 20px;\n  color: var(--text-secondary);\n  font-size: var(--body-sm-font-size);\n  line-height: 20px;\n}\n\n.pbe-figure {\n  color: var(--text-default);\n  font-family: var(--font-family-metric);\n  font-variant-numeric: tabular-nums;\n  font-weight: 500;\n}\n\n.pbe-mono {\n  font-family: var(--code-editor-font-family);\n  font-variant-numeric: tabular-nums;\n}\n\n/* ── toolbar (filter / search, single row, labels inline) ──────────────── */\n\n.pbe-toolbar {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: var(--spacer-12);\n  margin-bottom: var(--spacer-16);\n}\n\n.pbe-toolbar__label {\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  white-space: nowrap;\n}\n\n.pbe-toolbar__right {\n  display: flex;\n  align-items: center;\n  gap: var(--spacer-8);\n  margin-left: auto;\n}\n\n/* ── table ─────────────────────────────────────────────────────────────── */\n\n.pbe-table-wrap {\n  overflow: hidden;\n  border: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-12);\n  background: var(--bg-base-default);\n}\n\n.pbe-table .ant-table {\n  background: transparent;\n}\n\n.pbe-table .ant-table-thead > tr > th {\n  background: transparent;\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  font-weight: 500;\n  letter-spacing: var(--body-sm-letter-spacing);\n  border-bottom: 1px solid var(--border-neutral-l1);\n}\n\n.pbe-table .ant-table-thead > tr > th::before {\n  display: none;\n}\n\n.pbe-table .ant-table-tbody > tr > td {\n  border-bottom: 1px solid var(--border-neutral-l1);\n}\n\n.pbe-table .ant-table-tbody > tr:last-child > td {\n  border-bottom: 0;\n}\n\n.pbe-table .ant-table-tbody > tr {\n  cursor: pointer;\n}\n\n/* The row itself is the drill-down\'s link; a keyboard user must be able to\n   see where they are before pressing Enter on it. */\n.pbe-table .ant-table-tbody > tr:focus-visible {\n  outline: 2px solid var(--border-brand);\n  outline-offset: -2px;\n}\n\n.pbe-table__foot {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: var(--spacer-12);\n  padding: var(--spacer-12) var(--spacer-16);\n  border-top: 1px solid var(--border-neutral-l1);\n  color: var(--text-secondary);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-cell-title {\n  color: var(--text-default);\n  font-weight: 500;\n  white-space: nowrap;\n  overflow: hidden;\n  text-overflow: ellipsis;\n}\n\n.pbe-cell-sub {\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  line-height: var(--body-sm-line-height);\n  white-space: nowrap;\n  overflow: hidden;\n  text-overflow: ellipsis;\n}\n\n/* ── disclosure ────────────────────────────────────────────────────────── */\n\n/* A long block that opens closed.  The whole row is the button -- a 12px\n   chevron is a mean target -- and the state sits at the right end, after the\n   reader has decided the block is worth opening.  The label stays flush left\n   with the other sub-labels it sits among. */\n.pbe-disclosure {\n  display: flex;\n  width: 100%;\n  align-items: center;\n  gap: var(--spacer-8);\n  margin: 0;\n  padding: var(--spacer-4) 0;\n  border: 0;\n  background: transparent;\n  color: var(--text-tertiary);\n  font-family: inherit;\n  font-size: var(--body-sm-font-size);\n  line-height: var(--body-sm-line-height);\n  text-align: left;\n  cursor: pointer;\n}\n\n.pbe-disclosure:focus-visible {\n  outline: 2px solid var(--border-brand);\n  outline-offset: 2px;\n  border-radius: var(--radius-4);\n}\n\n.pbe-disclosure__label {\n  color: var(--text-secondary);\n}\n\n.pbe-disclosure__note {\n  margin-left: auto;\n  color: var(--text-tertiary);\n  font-variant-numeric: tabular-nums;\n}\n\n.pbe-disclosure__act {\n  color: var(--text-tertiary);\n}\n\n.pbe-disclosure__chevron {\n  flex: none;\n  color: var(--text-tertiary);\n  transition: transform 140ms ease;\n}\n\n.pbe-disclosure:hover .pbe-disclosure__label,\n.pbe-disclosure:hover .pbe-disclosure__act,\n.pbe-disclosure:hover .pbe-disclosure__chevron {\n  color: var(--text-default);\n}\n\n.pbe-disclosure[aria-expanded="true"] .pbe-disclosure__chevron {\n  transform: rotate(90deg);\n}\n\n@media (prefers-reduced-motion: reduce) {\n  .pbe-disclosure__chevron {\n    transition: none;\n  }\n}\n\n/* ── report ────────────────────────────────────────────────────────────── */\n\n.pbe-meta {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: var(--spacer-8);\n  margin-top: var(--spacer-8);\n  color: var(--text-secondary);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-meta__sep {\n  color: var(--text-tertiary);\n}\n\n.pbe-scoreboard {\n  display: grid;\n  grid-template-columns: repeat(4, minmax(0, 1fr));\n  margin-bottom: var(--spacer-24);\n}\n\n@media (max-width: 900px) {\n  .pbe-scoreboard {\n    grid-template-columns: repeat(2, minmax(0, 1fr));\n  }\n}\n\n.pbe-scoreboard__cell {\n  padding: 0 var(--spacer-16);\n  border-left: 1px solid var(--border-neutral-l1);\n}\n\n.pbe-scoreboard__cell:first-child {\n  border-left: 0;\n  padding-left: 0;\n}\n\n.pbe-scoreboard__label {\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-scoreboard__value {\n  margin-top: var(--spacer-4);\n  color: var(--text-default);\n  font-family: var(--font-family-metric);\n  font-variant-numeric: tabular-nums;\n  font-size: var(--heading-md-font-size, 20px);\n  font-weight: 600;\n}\n\n.pbe-block {\n  padding: var(--spacer-12) var(--spacer-16);\n  border: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-8);\n  background: var(--bg-base-tertiary);\n  color: var(--text-default);\n  font-family: var(--code-editor-font-family);\n  font-size: var(--body-sm-font-size);\n  line-height: 1.6;\n  white-space: pre-wrap;\n  word-break: break-word;\n  overflow-x: auto;\n}\n\n.pbe-prompt {\n  max-height: 320px;\n  overflow-y: auto;\n  margin: 0;\n}\n\n.pbe-facts {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));\n  gap: var(--spacer-12) var(--spacer-24);\n}\n\n@media (max-width: 760px) {\n  .pbe-facts {\n    grid-template-columns: minmax(0, 1fr);\n  }\n}\n\n.pbe-fact__label {\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-fact__value {\n  margin-top: 2px;\n  color: var(--text-default);\n  word-break: break-word;\n}\n\n.pbe-rows {\n  display: flex;\n  flex-direction: column;\n}\n\n.pbe-row {\n  display: flex;\n  align-items: center;\n  gap: var(--spacer-12);\n  padding: var(--spacer-8) 0;\n  border-bottom: 1px solid var(--border-neutral-l1);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-row:last-child {\n  border-bottom: 0;\n}\n\n.pbe-row__grow {\n  flex: 1 1 auto;\n  min-width: 0;\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n\n/*\n * A row whose bytes can be opened.  It is a real `<button>` -- so it takes\n * focus and answers the keyboard -- which means undoing the browser\'s default\n * chrome rather than decorating a div, and keeping the row\'s own box so the\n * list does not jump when only some rows are openable.\n */\n.pbe-row--file {\n  width: calc(100% + var(--spacer-16));\n  margin: 0 calc(var(--spacer-8) * -1);\n  border: 0;\n  border-bottom: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-4);\n  background: none;\n  color: inherit;\n  font: inherit;\n  text-align: left;\n  cursor: pointer;\n  padding-left: var(--spacer-8);\n  padding-right: var(--spacer-8);\n}\n\n.pbe-row--file:hover {\n  background: var(--bg-card-hover);\n}\n\n.pbe-row--file:focus-visible {\n  outline: 2px solid var(--border-brand);\n  outline-offset: -2px;\n}\n\n.pbe-section-title {\n  margin: 0 0 var(--spacer-12);\n  color: var(--text-default);\n  font-size: var(--body-base-font-size);\n  font-weight: 600;\n}\n\n/* ── trace (one run, read in order) ────────────────────────────────────── */\n\n/*\n * A console, not a page section: the toolbar and the position stay put while\n * the run scrolls under them.  That is the one thing the old table got right by\n * accident (its rows were short) and the thing a 200-row page needs most.\n */\n.pbe-trace {\n  border: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-12);\n  background: var(--bg-base-default);\n  overflow: hidden;\n}\n\n.pbe-trace__bar {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: var(--spacer-12);\n  padding: var(--spacer-8) var(--spacer-12);\n  border-bottom: 1px solid var(--border-neutral-l1);\n  background: var(--bg-base-secondary);\n}\n\n.pbe-trace__nav {\n  display: flex;\n  align-items: center;\n  gap: var(--spacer-8);\n  margin-left: auto;\n}\n\n.pbe-trace__pos {\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  font-variant-numeric: tabular-nums;\n  white-space: nowrap;\n}\n\n.pbe-trace__error {\n  padding: var(--spacer-6) var(--spacer-12);\n  border-bottom: 1px solid var(--border-neutral-l1);\n  color: var(--status-error-default);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-trace__scroll {\n  max-height: min(56vh, 560px);\n  padding: var(--spacer-16) var(--spacer-16) var(--spacer-8);\n  overflow-y: auto;\n  overscroll-behavior: contain;\n}\n\n.pbe-trace__scroll[aria-busy="true"] {\n  opacity: 0.5;\n  transition: opacity 120ms ease;\n}\n\n.pbe-trace__quiet {\n  max-width: 62ch;\n  padding: var(--spacer-24) var(--spacer-8);\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  line-height: 1.8;\n}\n\n.pbe-trace__foot {\n  display: flex;\n  align-items: center;\n  justify-content: space-between;\n  gap: var(--spacer-12);\n  padding: var(--spacer-8) var(--spacer-12);\n  border-top: 1px solid var(--border-neutral-l1);\n  background: var(--bg-base-secondary);\n}\n\n/* one beat on the rail */\n\n.pbe-beat {\n  display: grid;\n  grid-template-columns: 16px minmax(0, 1fr);\n  gap: 0 var(--spacer-12);\n}\n\n.pbe-beat__rail {\n  position: relative;\n  display: flex;\n  justify-content: center;\n}\n\n/*\n * The line is drawn per beat and runs the full height of the gutter, so two\n * adjacent beats join without a seam.  The first starts below its dot and the\n * last stops at it, which is what keeps the rail from overshooting the run.\n * At the hairline weight the lighter border token is invisible once the page is\n * scrolled -- the spine is what tells a reader these rows are one run.\n */\n.pbe-beat__rail::before {\n  content: "";\n  position: absolute;\n  top: -2px;\n  bottom: 0;\n  left: 50%;\n  width: 1px;\n  margin-left: -0.5px;\n  background: var(--border-neutral-l3);\n}\n\n.pbe-beat:first-child .pbe-beat__rail::before {\n  top: 9px;\n}\n\n.pbe-beat:last-child .pbe-beat__rail::before {\n  bottom: auto;\n  height: 9px;\n}\n\n.pbe-beat:only-child .pbe-beat__rail::before {\n  display: none;\n}\n\n.pbe-beat__dot {\n  position: relative;\n  z-index: 1;\n  width: 7px;\n  height: 7px;\n  margin-top: 7px;\n  border-radius: 2px;\n  background: var(--text-disabled);\n  box-shadow: 0 0 0 3px var(--bg-base-default);\n}\n\n.pbe-beat__rail--user .pbe-beat__dot {\n  background: var(--text-secondary);\n}\n\n.pbe-beat__rail--assistant .pbe-beat__dot {\n  background: var(--bg-brand);\n}\n\n.pbe-beat__rail--tool .pbe-beat__dot {\n  box-sizing: border-box;\n  background: var(--bg-base-default);\n  border: 1.5px solid var(--border-neutral-l3);\n}\n\n.pbe-beat__rail--thought .pbe-beat__dot {\n  width: 5px;\n  height: 5px;\n  margin-top: 8px;\n}\n\n.pbe-beat__rail--plan .pbe-beat__dot {\n  background: var(--accent-teal);\n}\n\n.pbe-beat__rail--system .pbe-beat__dot {\n  width: 5px;\n  height: 5px;\n  margin-top: 8px;\n  background: var(--border-neutral-l3);\n}\n\n.pbe-beat__body {\n  min-width: 0;\n  padding-bottom: var(--spacer-16);\n}\n\n.pbe-beat__meta {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: var(--spacer-8);\n  min-height: 20px;\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  line-height: 20px;\n}\n\n.pbe-beat__who {\n  color: var(--text-secondary);\n  font-weight: 500;\n}\n\n.pbe-beat__quiet {\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  line-height: 1.7;\n}\n\n/* words: prose on the page, not a box per turn */\n\n.pbe-speech {\n  max-width: 74ch;\n  color: var(--text-default);\n  font-size: var(--body-base-font-size);\n  line-height: 1.72;\n  letter-spacing: -0.01em;\n  white-space: pre-wrap;\n  word-break: break-word;\n}\n\n.pbe-thought {\n  max-width: 74ch;\n  max-height: 3.4em;\n  overflow: hidden;\n  color: var(--text-tertiary);\n  font-size: var(--body-md-font-size, 12px);\n  line-height: 1.75;\n  white-space: pre-wrap;\n  word-break: break-word;\n  /* A fade on the text of a collapsed thought, not a colour: the mask only\n     reads alpha, so `black` here is "opaque" and takes no value from the tokens. */\n  -webkit-mask-image: linear-gradient(180deg, black 55%, transparent);\n  mask-image: linear-gradient(180deg, black 55%, transparent);\n}\n\n.pbe-thought--open {\n  max-height: none;\n  -webkit-mask-image: none;\n  mask-image: none;\n}\n\n/* a tool call: identity on the head, arguments as fields, result attached */\n\n.pbe-tool {\n  /* One column for every label in the card: argument names and "结果".  Wide\n     enough for a field like ``command``, narrow enough that a short one is not\n     stranded in the middle of the card. */\n  --pbe-tool-key: 84px;\n  padding: var(--spacer-10) var(--spacer-12);\n  border: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-8);\n  background: var(--bg-base-secondary);\n}\n\n.pbe-tool__head {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: var(--spacer-8);\n  min-height: 22px;\n}\n\n/* A failed call is the one thing in a run that must survive a skim. */\n.pbe-tool--failed {\n  border-color: var(--status-error-surface-l3);\n  background: var(--status-error-surface-l1);\n}\n\n.pbe-tool__title {\n  color: var(--text-default);\n  font-size: var(--body-base-font-size);\n  font-weight: 500;\n}\n\n.pbe-tool__name {\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-tool__size {\n  margin-left: auto;\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  font-variant-numeric: tabular-nums;\n}\n\n.pbe-tool__args {\n  display: flex;\n  flex-direction: column;\n  gap: 2px;\n  margin-top: var(--spacer-6);\n}\n\n.pbe-tool__arg {\n  display: grid;\n  grid-template-columns: var(--pbe-tool-key) minmax(0, 1fr);\n  gap: var(--spacer-8);\n  font-size: var(--body-sm-font-size);\n  line-height: 18px;\n}\n\n.pbe-tool__key {\n  overflow: hidden;\n  color: var(--text-tertiary);\n  text-align: right;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n\n.pbe-tool__value {\n  overflow: hidden;\n  color: var(--text-secondary);\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n\n.pbe-tool__value--wrap {\n  white-space: pre-wrap;\n  word-break: break-word;\n}\n\n/* Arguments and the result share one left column, so the card reads as a single\n   key/value table rather than as two blocks indented differently. */\n\n.pbe-tool__out {\n  display: grid;\n  grid-template-columns: var(--pbe-tool-key) minmax(0, 1fr);\n  gap: var(--spacer-8);\n  margin-top: var(--spacer-8);\n}\n\n.pbe-tool__out-label {\n  padding-top: var(--spacer-6);\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  line-height: 18px;\n  text-align: right;\n}\n\n.pbe-tool__out-text {\n  min-width: 0;\n  max-height: 84px;\n  margin: 0;\n  padding: var(--spacer-6) var(--spacer-10);\n  overflow: hidden;\n  border-left: 2px solid var(--border-neutral-l2);\n  border-radius: 0 var(--radius-4) var(--radius-4) 0;\n  background: var(--bg-base-default);\n  color: var(--text-secondary);\n  font-family: var(--code-editor-font-family);\n  font-size: 11px;\n  line-height: 1.65;\n  white-space: pre-wrap;\n  word-break: break-word;\n}\n\n/* Once opened the reader asked for the whole result: no clamp, no scroll box\n   hiding the tail behind a scrollbar that looks like "the end". */\n.pbe-tool__out--open .pbe-tool__out-text {\n  max-height: none;\n  overflow: visible;\n  white-space: pre-wrap;\n  word-break: break-word;\n}\n\n/* The control lives in one slot on every meta row, so "展开" and "收起" keep\n   the same baseline and the same right edge no matter how long the content is. */\n.pbe-beat__more-slot {\n  display: inline-flex;\n  margin-left: auto;\n  justify-content: flex-end;\n}\n\n.pbe-beat__more {\n  display: inline-flex;\n  align-items: center;\n  justify-content: center;\n  min-width: 96px;\n  min-height: 20px;\n  margin: 0;\n  padding: 0 var(--spacer-8);\n  border: 0;\n  border-radius: var(--radius-4);\n  background: none;\n  color: var(--text-brand);\n  font: inherit;\n  font-size: var(--body-sm-font-size);\n  line-height: 18px;\n  white-space: nowrap;\n  cursor: pointer;\n}\n\n.pbe-beat__more--open,\n.pbe-beat__more:disabled {\n  color: var(--text-tertiary);\n}\n\n.pbe-beat__more:disabled {\n  cursor: default;\n}\n\n.pbe-beat__more:hover:not(:disabled) {\n  text-decoration: underline;\n}\n\n.pbe-beat__more:focus-visible {\n  outline: 2px solid var(--border-brand);\n  outline-offset: 2px;\n}\n\n/* a plan is a checklist, because that is what the agent wrote */\n\n.pbe-plan {\n  display: flex;\n  flex-direction: column;\n  gap: var(--spacer-4);\n  max-width: 74ch;\n  margin: var(--spacer-6) 0 0;\n  padding: 0;\n  list-style: none;\n  font-size: var(--body-base-font-size);\n  line-height: 1.6;\n}\n\n.pbe-plan__item {\n  display: grid;\n  grid-template-columns: 16px minmax(0, 1fr);\n  gap: var(--spacer-6);\n  color: var(--text-secondary);\n}\n\n.pbe-plan__mark {\n  color: var(--text-tertiary);\n  text-align: center;\n}\n\n.pbe-plan__item--completed {\n  color: var(--text-tertiary);\n  text-decoration: line-through;\n  text-decoration-color: var(--border-neutral-l3);\n}\n\n.pbe-plan__item--completed .pbe-plan__mark {\n  color: var(--status-success-default);\n}\n\n.pbe-plan__item--in_progress {\n  color: var(--text-default);\n}\n\n.pbe-plan__item--in_progress .pbe-plan__mark {\n  color: var(--text-brand);\n}\n\n/* UI chatter folds into one line */\n\n.pbe-system {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  gap: var(--spacer-8);\n  padding: 0;\n  border: 0;\n  border-radius: var(--radius-4);\n  background: none;\n  color: var(--text-tertiary);\n  font: inherit;\n  font-size: var(--body-sm-font-size);\n  cursor: pointer;\n}\n\n.pbe-system:hover {\n  color: var(--text-secondary);\n}\n\n.pbe-system:focus-visible {\n  outline: 2px solid var(--border-brand);\n  outline-offset: 2px;\n}\n\n.pbe-system__act {\n  margin-left: auto;\n  color: var(--text-brand);\n}\n\n.pbe-system__list {\n  margin: var(--spacer-4) 0 0;\n  padding-left: var(--spacer-16);\n  color: var(--text-tertiary);\n  font-size: 11px;\n  line-height: 1.7;\n}\n\n@media (max-width: 760px) {\n  .pbe-trace__bar {\n    align-items: stretch;\n  }\n\n  .pbe-trace__nav {\n    width: 100%;\n    margin-left: 0;\n    justify-content: space-between;\n  }\n\n  .pbe-trace__scroll {\n    max-height: 60vh;\n    padding: var(--spacer-12);\n  }\n\n  .pbe-tool__arg {\n    grid-template-columns: minmax(0, 1fr);\n    gap: 0;\n  }\n\n  .pbe-tool__key {\n    text-align: left;\n  }\n\n  /* No room for a label column: the label goes above its value, and the result\n     block keeps the full width it needs to be readable. */\n  .pbe-tool__out {\n    grid-template-columns: minmax(0, 1fr);\n    gap: var(--spacer-4);\n  }\n\n  .pbe-tool__out-label {\n    padding-top: 0;\n    text-align: left;\n  }\n}\n\n@media (prefers-reduced-motion: reduce) {\n  .pbe-trace__scroll[aria-busy="true"] {\n    transition: none;\n  }\n}\n\n/* ── form (label left, control right — the system default) ─────────────── */\n\n.pbe-field {\n  display: flex;\n  align-items: flex-start;\n  gap: var(--spacer-12);\n  margin-bottom: var(--spacer-16);\n}\n\n.pbe-field__label {\n  flex: none;\n  width: 92px;\n  padding-top: var(--spacer-6);\n  color: var(--text-secondary);\n  font-size: var(--body-base-font-size);\n  text-align: right;\n}\n\n.pbe-field__control {\n  flex: 1 1 auto;\n  min-width: 0;\n}\n\n.pbe-field__hint {\n  margin-top: var(--spacer-4);\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n}\n\n.pbe-fieldset {\n  margin-bottom: var(--spacer-24);\n}\n\n.pbe-fieldset__title {\n  margin-bottom: var(--spacer-12);\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n  letter-spacing: 0.04em;\n}\n\n.pbe-empty {\n  padding: var(--spacer-32);\n  color: var(--text-tertiary);\n  text-align: center;\n}\n\n.pbe-copy {\n  display: inline-flex;\n  align-items: center;\n  gap: var(--spacer-6);\n  max-width: 100%;\n  padding: 0;\n  border: 0;\n  background: transparent;\n  color: var(--text-secondary);\n  font-family: var(--code-editor-font-family);\n  font-size: var(--body-sm-font-size);\n  cursor: pointer;\n}\n\n.pbe-copy:hover {\n  color: var(--text-default);\n}\n\n.pbe-copy__value {\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n\n/* ── status pill ───────────────────────────────────────────────────────── */\n\n.pbe-pill {\n  display: inline-flex;\n  align-items: center;\n  gap: var(--spacer-6);\n  height: 20px;\n  padding: 0 var(--spacer-8);\n  border: 1px solid transparent;\n  border-radius: var(--radius-4);\n  font-size: var(--body-xs-font-size);\n  line-height: 20px;\n  white-space: nowrap;\n}\n\n.pbe-pill__dot {\n  width: 6px;\n  height: 6px;\n  border-radius: 999px;\n  background: currentColor;\n}\n\n.pbe-pill--ok {\n  background: var(--status-success-surface-l1);\n  color: var(--status-success-default);\n}\n\n.pbe-pill--warn {\n  background: var(--status-warning-surface-l1);\n  color: var(--status-warning-default);\n}\n\n.pbe-pill--err {\n  background: var(--status-error-surface-l1);\n  color: var(--status-error-default);\n}\n\n.pbe-pill--info {\n  background: var(--status-primary-surface-l1);\n  color: var(--status-primary-default);\n}\n\n.pbe-pill--muted {\n  background: var(--bg-overlay-l1);\n  color: var(--text-secondary);\n}\n\n/* ── one file, opened ──────────────────────────────────────────────────── */\n\n.pbe-preview__title {\n  display: flex;\n  align-items: baseline;\n  gap: var(--spacer-12);\n  min-width: 0;\n}\n\n.pbe-preview__title > .pbe-mono {\n  overflow: hidden;\n  text-overflow: ellipsis;\n  white-space: nowrap;\n}\n\n/*\n * The height is a ceiling, not a size: a short file should make a short\n * dialog, and a long one should scroll inside this box instead of pushing the\n * footer off the screen.\n */\n.pbe-preview {\n  max-height: 58vh;\n  margin: 0;\n  overflow: auto;\n  white-space: pre-wrap;\n  word-break: break-word;\n}\n\n.pbe-preview__image {\n  display: block;\n  max-width: 100%;\n  max-height: 58vh;\n  margin: 0 auto;\n  border: 1px solid var(--border-neutral-l1);\n  border-radius: var(--radius-8);\n  background: var(--bg-base-tertiary);\n  object-fit: contain;\n}\n\n/* Why the text below stops where it stops.  Above the block, because a reader\n   who starts scrolling should meet it before the scrollbar, not after. */\n.pbe-preview__note {\n  margin-bottom: var(--spacer-8);\n  color: var(--text-tertiary);\n  font-size: var(--body-sm-font-size);\n}\n';

// src/host/sdk.ts
var API_BASE = "/pawbench-eval";
function host() {
  const sdk = window.QwenPaw?.host;
  if (!sdk) {
    throw new Error("window.QwenPaw.host is not ready");
  }
  return sdk;
}
function icons() {
  return host().antdIcons ?? {};
}
var HttpError = class extends Error {
  constructor(status, message2, code = "", details = null) {
    super(message2);
    this.name = "HttpError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
};
function authHeaders() {
  const token = typeof host().getApiToken === "function" ? host().getApiToken() : "";
  return token ? { Authorization: `Bearer ${token}` } : {};
}
async function readResponse(response) {
  const text = await response.text();
  let data = null;
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
      data && (data.message || data.error) || `HTTP ${response.status}`,
      data && data.error || "",
      (data && data.details) ?? null
    );
  }
  return data;
}
async function call(method, path, body) {
  const response = await fetch(host().getApiUrl(API_BASE + path), {
    method,
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: body === void 0 ? void 0 : JSON.stringify(body)
  });
  return readResponse(response);
}
async function uploadRaw(path, file) {
  const response = await fetch(host().getApiUrl(API_BASE + path), {
    method: "POST",
    headers: { "Content-Type": "application/zip", ...authHeaders() },
    body: file
  });
  return readResponse(response);
}
async function download(path, filename) {
  const response = await fetch(host().getApiUrl(API_BASE + path), { headers: authHeaders() });
  if (!response.ok) {
    throw new HttpError(response.status, `HTTP ${response.status}`);
  }
  saveBlob(await response.blob(), filename);
}
function saveBlob(blob, filename) {
  const href = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename || "download";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  window.setTimeout(() => URL.revokeObjectURL(href), 2e3);
}
async function copyText(value, label) {
  if (!value) return false;
  try {
    if (navigator.clipboard) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch {
  }
  return false;
}
function describeError(error) {
  if (error instanceof HttpError) {
    return { code: error.code || `http_${error.status}`, message: error.message };
  }
  return { code: "unexpected_error", message: String(error?.message ?? error) };
}

// src/host/antd.ts
var antd = window.QwenPaw?.host?.antd;
var Alert = antd.Alert;
var App = antd.App;
var Button = antd.Button;
var ConfigProvider = antd.ConfigProvider;
var DatePicker = antd.DatePicker;
var Drawer = antd.Drawer;
var Empty = antd.Empty;
var Form = antd.Form;
var Input = antd.Input;
var InputNumber = antd.InputNumber;
var Modal = antd.Modal;
var Pagination = antd.Pagination;
var Popconfirm = antd.Popconfirm;
var Progress = antd.Progress;
var Radio = antd.Radio;
var Segmented = antd.Segmented;
var Select = antd.Select;
var Skeleton = antd.Skeleton;
var Space = antd.Space;
var Spin = antd.Spin;
var Switch = antd.Switch;
var Table = antd.Table;
var Tabs = antd.Tabs;
var Tag = antd.Tag;
var Tooltip = antd.Tooltip;
var Typography = antd.Typography;
var Upload = antd.Upload;
var message = antd.message;
var theme = antd.theme;
var Text = Typography.Text;
var Title = Typography.Title;
var Paragraph = Typography.Paragraph;

// src/api.ts
var BeatFilters = [
  { value: "all", label: "全部" },
  { value: "talk", label: "对话" },
  { value: "tool", label: "工具" },
  { value: "thought", label: "思考" },
  { value: "plan", label: "计划" }
];
var q = encodeURIComponent;
var api = {
  config: () => call("GET", "/config"),
  saveConfig: (body) => call("PUT", "/config", body),
  probe: () => call("POST", "/config/probe", {}),
  learnIdentity: (jobId) => call("POST", `/identity/${q(jobId)}`, {}),
  jobs: () => call("GET", "/v1/jobs"),
  job: (jobId) => call("GET", `/v1/jobs/${q(jobId)}`),
  submit: (body) => call("POST", "/v1/jobs", body),
  reorder: (jobId, target) => call("PATCH", `/v1/jobs/${q(jobId)}`, target),
  cancel: (jobId, reason) => call("POST", `/v1/jobs/${q(jobId)}/cancel`, { reason }),
  detail: (jobId) => call("GET", `/v1/jobs/${q(jobId)}/detail`),
  taskDetail: (jobId, taskId, attempt) => call(
    "GET",
    `/v1/jobs/${q(jobId)}/tasks/${q(taskId)}/detail?attempt=${attempt}`
  ),
  results: (jobId) => call("GET", `/v1/jobs/${q(jobId)}/results`),
  /**
   * One page of a task's timeline.
   *
   * ``detail`` asks for the readable version -- bounded previews of speech and
   * tool results -- because the dashboard is where a person argues with a score
   * and "340 chars" cannot be argued with.  The judge-facing callers leave it
   * off and keep the size-only page.
   */
  transcript: (jobId, taskId, attempt, cursor, detail = false) => call(
    "GET",
    `/v1/jobs/${q(jobId)}/transcript?task_id=${q(taskId)}&attempt=${attempt}&cursor=${cursor}` + (detail ? "&detail=1" : "")
  ),
  /**
   * One page of the run's beats, folded on the service.
   *
   * The reader pages by beat -- ten sentences, not ten notifications -- and
   * filters on the same folded list, so a page of "工具" holds ten tool calls
   * rather than ten lines of which none may be a tool.  Raw line cursors stay
   * behind the service; a beat is named by its index in the filtered list.
   */
  beats: (jobId, taskId, attempt, page, size, voice) => call(
    "GET",
    `/v1/jobs/${q(jobId)}/beats?task_id=${q(taskId)}&attempt=${attempt}&page=${page}&size=${size}&voice=${q(voice)}`
  ),
  /** Complete text, arguments and result of one opened beat. */
  beatContent: (jobId, taskId, attempt, index, voice) => call(
    "GET",
    `/v1/jobs/${q(jobId)}/beats/content?task_id=${q(taskId)}&attempt=${attempt}&index=${index}&voice=${q(voice)}`
  ),
  /**
   * One file's contents, trimmed.
   *
   * Two paths rather than one with a `kind` query: an artifact and an
   * attachment are two different files, and the caller always knows which one
   * it is holding.
   */
  preview: (jobId, taskId, attempt, kind, path) => call(
    "GET",
    `/v1/jobs/${q(jobId)}/tasks/${q(taskId)}/attempts/${attempt}/${kind}/preview?path=${q(path)}`
  ),
  /** Where a download goes, so the proxy can add the token on the way out. */
  fileUrl: (jobId, taskId, attempt, kind, path) => `/v1/jobs/${jobId}/tasks/${taskId}/attempts/${attempt}/${kind}?path=${q(path)}`,
  report: (jobId, format) => call("GET", `/v1/jobs/${q(jobId)}/report?format=${format}`),
  datasets: () => call("GET", "/v1/datasets"),
  datasetDetail: (datasetId) => call("GET", `/v1/datasets/${q(datasetId)}`),
  datasetTask: (datasetId, taskId) => call("GET", `/v1/datasets/${q(datasetId)}/tasks/${q(taskId)}`),
  /**
   * A fixture's contents, before any run exists.
   *
   * The same shape an artifact preview answers with, from the same function in
   * the service: the file a task comes with and the file an agent wrote back
   * are read with one set of rules.
   */
  datasetFixture: (datasetId, taskId, path) => call(
    "GET",
    `/v1/datasets/${q(datasetId)}/tasks/${q(taskId)}/attachments/preview?path=${q(path)}`
  ),
  /**
   * The task's own markdown.
   *
   * The fallback the detail page offers beside the parsed fields: if a rubric
   * resists parsing, the file itself is one click away.  Previewed through the
   * same reader as a fixture, so the trim is the same.
   */
  datasetTaskSource: (datasetId, taskId) => call("GET", `/v1/datasets/${q(datasetId)}/tasks/${q(taskId)}/source`),
  /** Where a fixture download goes, so the proxy can add the token on the way out. */
  datasetFixtureUrl: (datasetId, taskId, path) => `/v1/datasets/${q(datasetId)}/tasks/${q(taskId)}/attachments?path=${q(path)}`,
  categories: () => call("GET", "/v1/dataset-categories"),
  resolve: (selector) => call("POST", "/v1/datasets/resolve", { selector }),
  createDataset: (body) => call("POST", "/v1/datasets", body),
  editDataset: (datasetId, body) => call("PUT", `/v1/datasets/${q(datasetId)}`, body),
  deleteDataset: (datasetId) => call("DELETE", `/v1/datasets/${q(datasetId)}`),
  uploadPackage: (file, query) => uploadRaw(`/v1/datasets/packages?${query}`, file),
  createCategory: (body) => call("POST", "/v1/dataset-categories", body),
  deleteCategory: (name) => call("DELETE", `/v1/dataset-categories/${q(name)}`)
};

// src/host/react.ts
var React2 = window.QwenPaw?.host?.React;
var useState = React2.useState;
var useEffect = React2.useEffect;
var useLayoutEffect = React2.useLayoutEffect;
var useMemo = React2.useMemo;
var useCallback = React2.useCallback;
var useRef = React2.useRef;

// src/theme.tsx
var TOKENS = [
  "--bg-base-default",
  "--bg-base-secondary",
  "--bg-base-tertiary",
  "--bg-menu",
  "--bg-brand",
  "--bg-brand-hover",
  "--bg-brand-active",
  "--bg-card-hover",
  "--bg-overlay-l1",
  "--bg-overlay-l2",
  "--bg-overlay-l3",
  "--bg-tooltip",
  "--border-neutral-l1",
  "--border-neutral-l2",
  "--border-neutral-l3",
  "--border-brand",
  "--border-contrast",
  "--text-default",
  "--text-secondary",
  "--text-tertiary",
  "--text-brand",
  "--text-onbrand",
  "--text-disabled",
  "--icon-default",
  "--icon-secondary",
  "--icon-tertiary",
  "--status-success-default",
  "--status-success-surface-l1",
  "--status-warning-default",
  "--status-warning-surface-l1",
  "--status-error-default",
  "--status-error-surface-l1",
  "--status-alert-default",
  "--status-alert-surface-l1",
  "--status-primary-default",
  "--status-primary-surface-l1",
  "--code-editor-font-family",
  "--font-family-metric",
  "--font-family-default",
  "--font-family-heading",
  "--body-base-font-size",
  "--body-base-line-height",
  "--body-sm-font-size",
  "--body-sm-line-height",
  "--heading-lg-font-size",
  "--heading-lg-line-height",
  "--radius-4",
  "--radius-8",
  "--radius-12",
  "--spacer-4",
  "--spacer-8",
  "--spacer-12",
  "--spacer-16",
  "--spacer-20",
  "--spacer-24",
  "--spacer-32",
  "--layout-sidebar"
];
function brightness(value) {
  const text = String(value || "").trim();
  let parts = [];
  if (text.startsWith("#")) {
    const hex = text.slice(1);
    const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex.slice(0, 6);
    parts = [
      parseInt(full.slice(0, 2), 16),
      parseInt(full.slice(2, 4), 16),
      parseInt(full.slice(4, 6), 16)
    ];
  } else {
    parts = (text.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
  }
  const [r = 255, g = 255, b = 255] = parts;
  return (0.2126 * (r || 0) + 0.7152 * (g || 0) + 0.0722 * (b || 0)) / 255;
}
function readTokens(element) {
  const styles = getComputedStyle(element);
  const read = {};
  for (const name of TOKENS) {
    const value = styles.getPropertyValue(name).trim();
    if (value) read[name] = value;
  }
  return read;
}
function antdTheme(tokens, isDark) {
  const t = tokens;
  return {
    algorithm: isDark ? theme.darkAlgorithm : theme.defaultAlgorithm,
    token: {
      colorPrimary: t["--bg-brand"],
      colorInfo: t["--status-primary-default"],
      colorSuccess: t["--status-success-default"],
      colorWarning: t["--status-warning-default"],
      colorError: t["--status-error-default"],
      colorText: t["--text-default"],
      colorTextSecondary: t["--text-secondary"],
      colorTextTertiary: t["--text-tertiary"],
      colorTextQuaternary: t["--text-tertiary"],
      colorTextDisabled: t["--text-disabled"],
      colorBgBase: t["--bg-base-default"],
      colorBgContainer: t["--bg-base-default"],
      colorBgElevated: t["--bg-menu"],
      colorBgLayout: t["--bg-base-secondary"],
      colorBorder: t["--border-neutral-l1"],
      colorBorderSecondary: t["--border-neutral-l1"],
      colorSplit: t["--border-neutral-l1"],
      colorFill: t["--bg-overlay-l1"],
      colorFillSecondary: t["--bg-overlay-l1"],
      colorFillTertiary: t["--bg-overlay-l1"],
      colorFillQuaternary: t["--bg-overlay-l1"],
      borderRadius: 8,
      borderRadiusLG: 12,
      borderRadiusSM: 4,
      borderRadiusXS: 4,
      fontFamily: t["--font-family-default"],
      fontFamilyCode: t["--code-editor-font-family"],
      fontSize: 14,
      controlHeight: 32,
      wireframe: false
    },
    components: {
      Table: {
        headerBg: "transparent",
        headerColor: t["--text-tertiary"],
        headerSplitColor: "transparent",
        borderColor: t["--border-neutral-l1"],
        rowHoverBg: t["--bg-overlay-l1"],
        cellPaddingBlock: 12,
        cellPaddingInline: 12
      },
      Tabs: {
        itemColor: t["--text-secondary"],
        itemHoverColor: t["--text-brand"],
        itemSelectedColor: t["--text-brand"],
        inkBarColor: t["--bg-brand"],
        titleFontSize: 14
      },
      Button: { primaryShadow: "none", defaultShadow: "none", dangerShadow: "none" },
      Modal: {
        contentBg: t["--bg-base-default"],
        headerBg: t["--bg-base-default"],
        titleColor: t["--text-default"]
      },
      Segmented: {
        trackBg: t["--bg-overlay-l1"],
        itemSelectedBg: t["--bg-base-default"],
        itemColor: t["--text-secondary"],
        itemSelectedColor: t["--text-default"]
      },
      Input: { activeShadow: "none" },
      Select: { optionSelectedBg: t["--bg-overlay-l2"] },
      Tooltip: { colorBgSpotlight: t["--bg-tooltip"] },
      // A progress fill is information, not an action: brand purple stays
      // reserved for the primary button and navigation, per the system.
      Progress: { defaultColor: t["--status-primary-default"] }
    }
  };
}
function DesignScope(props) {
  const hostToken = theme.useToken;
  const host2 = typeof hostToken === "function" ? hostToken().token : {};
  const isDark = brightness(String(host2.colorBgBase ?? "")) < 0.5;
  const attribute = isDark ? "dark" : "light";
  const [element, setElement] = useState(null);
  const [tokens, setTokens] = useState(null);
  useLayoutEffect(() => {
    const root = document.documentElement;
    const had = root.getAttribute("data-theme");
    root.setAttribute("data-theme", attribute);
    return () => {
      if (had === null) root.removeAttribute("data-theme");
      else root.setAttribute("data-theme", had);
    };
  }, [attribute]);
  useLayoutEffect(() => {
    if (!element) return;
    setTokens(readTokens(element));
  }, [element, attribute]);
  const themeConfig = useMemo(
    () => antdTheme(tokens ?? {}, isDark),
    [tokens, isDark]
  );
  const { ConfigProvider: ConfigProvider2 } = props;
  return /* @__PURE__ */ __h(
    "div",
    {
      className: props.className,
      "data-theme": attribute,
      "data-pbe-ready": tokens ? "true" : "false",
      ref: setElement,
      style: tokens ? void 0 : { visibility: "hidden" }
    },
    /* @__PURE__ */ __h(ConfigProvider2, { theme: themeConfig }, props.children)
  );
}

// src/ui/feedback.ts
var app = App;
function useFeedback() {
  const context = typeof app?.useApp === "function" ? app.useApp() : null;
  return {
    message: context?.message ?? message,
    modal: context?.modal ?? Modal
  };
}

// src/ui/primitives.tsx
function jobStatus(status) {
  switch (status) {
    case "running":
      return { tone: "info", label: "运行中" };
    case "queued":
      return { tone: "warn", label: "已排队" };
    case "scheduled":
      return { tone: "warn", label: "待起跑" };
    case "finished":
      return { tone: "ok", label: "已完成" };
    case "failed":
      return { tone: "err", label: "失败" };
    case "canceled":
      return { tone: "muted", label: "已取消" };
    case "new":
      return { tone: "muted", label: "已登记" };
    default:
      return { tone: "muted", label: status || "未知" };
  }
}
function taskStatus(status, failureReason) {
  if (failureReason) {
    return { tone: "err", label: failureReason };
  }
  switch (status) {
    case "skipped":
      return { tone: "err", label: "跳过" };
    case "no_artifacts":
      return { tone: "err", label: "无产物" };
    case "missing":
      return { tone: "err", label: "缺失" };
    default:
      return jobStatus(status);
  }
}
function StatusPill(props) {
  return /* @__PURE__ */ __h("span", { className: `pbe-pill pbe-pill--${props.tone}` }, /* @__PURE__ */ __h("span", { className: "pbe-pill__dot", "aria-hidden": "true" }), props.label);
}
function PageHead(props) {
  return /* @__PURE__ */ __h("div", { className: "pbe-head" }, /* @__PURE__ */ __h("div", { className: "pbe-head__text" }, /* @__PURE__ */ __h("h1", { className: "pbe-head__title" }, props.title), props.sub ? /* @__PURE__ */ __h("div", { className: "pbe-head__sub" }, props.sub) : null), props.actions ? /* @__PURE__ */ __h("div", { className: "pbe-head__actions" }, props.actions) : null);
}
function Panel(props) {
  const classes = ["pbe-panel"];
  if (props.pad !== false) classes.push("pbe-panel--pad");
  if (props.link) classes.push("pbe-panel--link");
  if (props.spanAll) classes.push("pbe-span-all");
  if (props.className) classes.push(props.className);
  return /* @__PURE__ */ __h("div", { className: classes.join(" "), onClick: props.onClick }, props.children);
}
function Figure(props) {
  return /* @__PURE__ */ __h("span", { className: "pbe-figure" }, props.value);
}
function SectionTitle(props) {
  return /* @__PURE__ */ __h("h2", { className: "pbe-section-title" }, props.children);
}
function Fact(props) {
  return /* @__PURE__ */ __h("div", null, /* @__PURE__ */ __h("div", { className: "pbe-fact__label" }, props.label), /* @__PURE__ */ __h("div", { className: "pbe-fact__value" }, props.value));
}
function CopyId(props) {
  const message2 = useFeedback().message;
  const [copied, setCopied] = useState(false);
  const value = String(props.value ?? "");
  if (!value) return /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, "—");
  const keep = props.keep ?? 12;
  const short = value.length > keep ? `${value.slice(0, keep)}…` : value;
  async function copy(event) {
    event.stopPropagation();
    const ok = await copyText(value, props.label ?? "id");
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
      message2.success(`已复制${props.label ? ` ${props.label}` : ""}`);
    } else {
      message2.info(value);
    }
  }
  return /* @__PURE__ */ __h(Tooltip, { title: copied ? "已复制" : `${props.label ?? "id"}：${value}（点击复制）` }, /* @__PURE__ */ __h("button", { type: "button", className: "pbe-copy", onClick: copy }, /* @__PURE__ */ __h("span", { className: "pbe-copy__value" }, short), /* @__PURE__ */ __h("span", { "aria-hidden": "true" }, "复制")));
}
function Field(props) {
  return /* @__PURE__ */ __h("div", { className: "pbe-field" }, /* @__PURE__ */ __h("label", { className: "pbe-field__label" }, props.label), /* @__PURE__ */ __h("div", { className: "pbe-field__control" }, props.children, props.hint ? /* @__PURE__ */ __h("div", { className: "pbe-field__hint" }, props.hint) : null));
}
function Fieldset(props) {
  return /* @__PURE__ */ __h("div", { className: "pbe-fieldset" }, /* @__PURE__ */ __h("div", { className: "pbe-fieldset__title" }, props.title), props.children);
}
function EmptyHint(props) {
  return /* @__PURE__ */ __h("div", { className: "pbe-empty" }, props.children);
}
function fixed(value, digits = 2) {
  if (value === null || value === void 0 || Number.isNaN(Number(value))) return "—";
  return Number(value).toFixed(digits);
}
function bytes(value) {
  if (!value) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
function duration(seconds) {
  if (seconds === null || seconds === void 0) return "—";
  const total = Math.max(0, Math.round(Number(seconds)));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest ? `${minutes}m ${rest}s` : `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
function stamp(value) {
  if (!value) return "—";
  return String(value).replace("T", " ").replace(/(\.\d+)?\+00:00$/, "").replace(/Z$/, "");
}
function json(value) {
  if (value === null || value === void 0) return "—";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

// src/modules/datasets.tsx
function DatasetsModule(props) {
  const feedback = useFeedback();
  const [datasets, setDatasets] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [viewOpen, setViewOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [categoryOpen, setCategoryOpen] = useState(false);
  const [search, setSearch] = useState("");
  async function load() {
    setLoading(true);
    try {
      const [list, cats] = await Promise.all([api.datasets(), api.categories()]);
      setDatasets(list.datasets);
      setCategories(cats.categories.map((item) => item.name));
      setError("");
    } catch (err) {
      const info = describeError(err);
      setError(`${info.code}：${info.message}`);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    void load();
  }, []);
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return datasets;
    return datasets.filter(
      (item) => [item.id, item.name, item.description, item.categories.join(" ")].join(" ").toLowerCase().includes(needle)
    );
  }, [datasets, search]);
  async function remove(item) {
    try {
      await api.deleteDataset(item.id);
      feedback.message.success(`已删除 ${item.id}`);
      void load();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    }
  }
  return /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(
    PageHead,
    {
      title: "数据集",
      sub: "内置视图是筛选快照，自定义包是上传的题目集；两者在提交页里混选。",
      actions: /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(Button, { onClick: () => void load(), loading }, "刷新"), /* @__PURE__ */ __h(Button, { onClick: () => setCategoryOpen(true) }, "管理分类"), /* @__PURE__ */ __h(Button, { onClick: () => setUploadOpen(true) }, "上传任务包"), /* @__PURE__ */ __h(Button, { type: "primary", onClick: () => setViewOpen(true) }, "新建视图"))
    }
  ), error ? /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, error)) : null, /* @__PURE__ */ __h("div", { className: "pbe-toolbar" }, /* @__PURE__ */ __h("span", { className: "pbe-toolbar__label" }, "搜索"), /* @__PURE__ */ __h(
    Input.Search,
    {
      allowClear: true,
      "aria-label": "搜索数据集",
      placeholder: "名称 / id / 分类 / 描述",
      style: { width: 280 },
      value: search,
      onChange: (event) => setSearch(event.target.value)
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-toolbar__right" }, /* @__PURE__ */ __h("span", { className: "pbe-toolbar__label" }, "共 ", datasets.length, " 个 · ", categories.length, " 个分类"))), /* @__PURE__ */ __h("div", { className: "pbe-table-wrap" }, /* @__PURE__ */ __h(
    Table,
    {
      className: "pbe-table",
      rowKey: "id",
      size: "middle",
      loading,
      dataSource: shown,
      pagination: { pageSize: 50, hideOnSinglePage: true },
      onRow: (item) => ({
        onClick: () => props.onOpen(item.id),
        // The row is the primary navigation of this page; a click-only row
        // puts it out of reach of a keyboard and of a screen reader.
        tabIndex: 0,
        onKeyDown: (event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            props.onOpen(item.id);
          }
        }
      }),
      locale: { emptyText: /* @__PURE__ */ __h(EmptyHint, null, "还没有数据集。可以上传一个任务包，或从内置语料里切一个视图。") },
      columns: [
        {
          title: "名称",
          dataIndex: "name",
          render: (_, item) => /* @__PURE__ */ __h("div", null, /* @__PURE__ */ __h("div", { className: "pbe-cell-title" }, item.name || item.id), /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, item.description || item.id))
        },
        {
          title: "类型",
          dataIndex: "kind",
          width: 130,
          render: (value) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, value === "builtin_view" ? "内置视图" : value === "custom_package" ? "自定义包" : value)
        },
        {
          title: "分类",
          dataIndex: "categories",
          width: 200,
          render: (value) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, (value ?? []).join("、") || "—")
        },
        {
          title: "题量",
          dataIndex: "task_count",
          width: 80,
          render: (value) => /* @__PURE__ */ __h("span", { className: "pbe-mono" }, value)
        },
        {
          title: "负责人",
          dataIndex: "owner",
          width: 110,
          render: (value) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, value)
        },
        {
          title: "更新",
          dataIndex: "updated_at",
          width: 150,
          render: (value) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, stamp(value))
        },
        {
          title: "操作",
          dataIndex: "id",
          width: 130,
          render: (_, item) => props.subject && item.owner === props.subject ? (
            // The cell stops the click: the row opens the dataset, and a
            // delete that also navigated would be a page change nobody
            // asked for behind a confirmation.
            /* @__PURE__ */ __h("div", { onClick: (event) => event.stopPropagation() }, /* @__PURE__ */ __h(
              Popconfirm,
              {
                title: "删除这个数据集？",
                description: "已经被作业引用过的数据集可能删不掉。",
                okText: "删除",
                cancelText: "不删",
                onConfirm: () => remove(item)
              },
              /* @__PURE__ */ __h(Button, { size: "small", type: "text", danger: true }, "删除")
            ))
          ) : /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, "只读")
        }
      ]
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-table__foot" }, /* @__PURE__ */ __h("span", null, "共 ", shown.length, " 条"), /* @__PURE__ */ __h("span", null, "点一行看题目清单；删除只对自己创建的行开放"))), /* @__PURE__ */ __h(
    CreateViewModal,
    {
      open: viewOpen,
      categories,
      onClose: () => setViewOpen(false),
      onDone: () => {
        setViewOpen(false);
        void load();
      }
    }
  ), /* @__PURE__ */ __h(
    UploadModal,
    {
      open: uploadOpen,
      categories,
      onClose: () => setUploadOpen(false),
      onDone: () => {
        setUploadOpen(false);
        void load();
      }
    }
  ), /* @__PURE__ */ __h(
    CategoryModal,
    {
      open: categoryOpen,
      categories,
      onClose: () => setCategoryOpen(false),
      onDone: () => void load()
    }
  ));
}
function CreateViewModal(props) {
  const feedback = useFeedback();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [scenario, setScenario] = useState("");
  const [capability, setCapability] = useState("");
  const [complexity, setComplexity] = useState("");
  const [filed, setFiled] = useState([]);
  const [busy, setBusy] = useState(false);
  async function submit() {
    const filter = {};
    if (scenario.trim()) filter.scenario = scenario.trim();
    if (capability.trim()) {
      filter.capability = capability.split(",").map((item) => item.trim()).filter(Boolean);
    }
    if (complexity.trim()) filter.complexity = complexity.trim();
    if (!Object.keys(filter).length) {
      feedback.message.error("至少要填一个筛选条件，否则等于整个语料");
      return;
    }
    setBusy(true);
    try {
      await api.createDataset({
        id: id.trim(),
        name: name.trim() || id.trim(),
        description: description.trim(),
        filter,
        categories: filed
      });
      feedback.message.success("视图已保存");
      setId("");
      setName("");
      setDescription("");
      setScenario("");
      setCapability("");
      setComplexity("");
      setFiled([]);
      props.onDone();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy(false);
    }
  }
  return /* @__PURE__ */ __h(
    Modal,
    {
      open: props.open,
      title: "新建内置视图",
      width: 620,
      onCancel: props.onClose,
      onOk: submit,
      okText: "保存视图",
      cancelText: "取消",
      confirmLoading: busy
    },
    /* @__PURE__ */ __h(Fieldset, { title: "标识" }, /* @__PURE__ */ __h(Field, { label: "id", hint: "小写字母、数字与下划线，保存后不可改" }, /* @__PURE__ */ __h(Input, { value: id, onChange: (event) => setId(event.target.value), placeholder: "如 regression_smoke" })), /* @__PURE__ */ __h(Field, { label: "名称" }, /* @__PURE__ */ __h(Input, { value: name, onChange: (event) => setName(event.target.value), placeholder: "给人看的名字" })), /* @__PURE__ */ __h(Field, { label: "描述" }, /* @__PURE__ */ __h(Input, { value: description, onChange: (event) => setDescription(event.target.value) }))),
    /* @__PURE__ */ __h(Fieldset, { title: "筛选（至少要有一项）" }, /* @__PURE__ */ __h(Field, { label: "场景", hint: "如 Software_Engineering/Code，留空表示不限" }, /* @__PURE__ */ __h(Input, { value: scenario, onChange: (event) => setScenario(event.target.value) })), /* @__PURE__ */ __h(Field, { label: "能力", hint: "多个用英文逗号分隔" }, /* @__PURE__ */ __h(Input, { value: capability, onChange: (event) => setCapability(event.target.value) })), /* @__PURE__ */ __h(Field, { label: "复杂度", hint: "L1 / L2 / L3" }, /* @__PURE__ */ __h(Input, { value: complexity, onChange: (event) => setComplexity(event.target.value) }))),
    /* @__PURE__ */ __h(Field, { label: "分类" }, /* @__PURE__ */ __h(
      Select,
      {
        mode: "tags",
        style: { width: "100%" },
        value: filed,
        onChange: (value) => setFiled(value),
        options: props.categories.map((name2) => ({ value: name2, label: name2 })),
        placeholder: "选已有分类，或直接输入新名字"
      }
    ))
  );
}
function UploadModal(props) {
  const feedback = useFeedback();
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [filed, setFiled] = useState([]);
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  async function submit() {
    if (!file) {
      feedback.message.error("先选一个 zip 任务包");
      return;
    }
    const query = new URLSearchParams();
    query.set("id", id.trim());
    query.set("name", name.trim() || id.trim());
    query.set("description", description.trim());
    for (const category of filed) query.append("categories", category);
    setBusy(true);
    try {
      await api.uploadPackage(file, query.toString());
      feedback.message.success("任务包已登记");
      setFile(null);
      setId("");
      setName("");
      setDescription("");
      setFiled([]);
      props.onDone();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy(false);
    }
  }
  return /* @__PURE__ */ __h(
    Modal,
    {
      open: props.open,
      title: "上传任务包",
      width: 620,
      onCancel: props.onClose,
      onOk: submit,
      okText: "上传并登记",
      cancelText: "取消",
      confirmLoading: busy
    },
    /* @__PURE__ */ __h(Field, { label: "zip 文件" }, /* @__PURE__ */ __h(
      "input",
      {
        type: "file",
        accept: ".zip",
        onChange: (event) => setFile(event.target.files?.[0] ?? null)
      }
    )),
    /* @__PURE__ */ __h(Field, { label: "id", hint: "登记后作为数据集 id，小写字母、数字与下划线" }, /* @__PURE__ */ __h(Input, { value: id, onChange: (event) => setId(event.target.value), placeholder: "如 office_batch_2" })),
    /* @__PURE__ */ __h(Field, { label: "名称" }, /* @__PURE__ */ __h(Input, { value: name, onChange: (event) => setName(event.target.value) })),
    /* @__PURE__ */ __h(Field, { label: "描述" }, /* @__PURE__ */ __h(Input, { value: description, onChange: (event) => setDescription(event.target.value) })),
    /* @__PURE__ */ __h(Field, { label: "分类" }, /* @__PURE__ */ __h(
      Select,
      {
        mode: "tags",
        style: { width: "100%" },
        value: filed,
        onChange: (value) => setFiled(value),
        options: props.categories.map((value) => ({ value, label: value }))
      }
    ))
  );
}
function CategoryModal(props) {
  const feedback = useFeedback();
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  async function add() {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await api.createCategory({ name: draft.trim() });
      setDraft("");
      feedback.message.success("分类已创建");
      props.onDone();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy(false);
    }
  }
  async function remove(name) {
    try {
      await api.deleteCategory(name);
      feedback.message.success(`已删除分类 ${name}`);
      props.onDone();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    }
  }
  return /* @__PURE__ */ __h(Modal, { open: props.open, title: "分类", width: 520, onCancel: props.onClose, footer: /* @__PURE__ */ __h(Button, { onClick: props.onClose }, "完成") }, /* @__PURE__ */ __h(Field, { label: "新分类", hint: "分类只用来归拢数据集，选中它等于选中其下所有数据集" }, /* @__PURE__ */ __h(
    Input.Search,
    {
      value: draft,
      onChange: (event) => setDraft(event.target.value),
      onSearch: add,
      enterButton: "创建",
      loading: busy
    }
  )), /* @__PURE__ */ __h("div", { className: "pbe-rows" }, props.categories.length ? props.categories.map((name) => /* @__PURE__ */ __h("div", { className: "pbe-row", key: name }, /* @__PURE__ */ __h("span", { className: "pbe-row__grow" }, /* @__PURE__ */ __h(CopyId, { value: name, label: "分类", keep: 40 })), /* @__PURE__ */ __h(Popconfirm, { title: "删除这个分类？", okText: "删除", cancelText: "不删", onConfirm: () => remove(name) }, /* @__PURE__ */ __h(Button, { size: "small", type: "text", danger: true }, "删除")))) : /* @__PURE__ */ __h(EmptyHint, null, "还没有分类")));
}

// src/ui/preview.tsx
function PreviewModal(props) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState("");
  const { kind, path } = props.target;
  const { source } = props;
  const sourceKey = JSON.stringify(source);
  useEffect(() => {
    let alive = true;
    setPreview(null);
    setError("");
    const asked = source.kind === "job" ? api.preview(source.jobId, source.taskId, source.attempt, kind, path) : kind === "source" ? api.datasetTaskSource(source.datasetId, source.taskId) : api.datasetFixture(source.datasetId, source.taskId, path);
    asked.then((answer) => {
      if (alive) setPreview(answer);
    }).catch((err) => {
      if (alive) setError(describeError(err).message);
    });
    return () => {
      alive = false;
    };
  }, [sourceKey, kind, path]);
  const name = path.split("/").pop() || path;
  function save() {
    const url = source.kind === "dataset" ? api.datasetFixtureUrl(source.datasetId, source.taskId, path) : kind === "artifacts" || kind === "attachments" ? api.fileUrl(source.jobId, source.taskId, source.attempt, kind, path) : "";
    if (url) {
      void download(url, name).catch((err) => setError(describeError(err).message));
    }
  }
  return /* @__PURE__ */ __h(
    Modal,
    {
      open: true,
      width: 920,
      onCancel: props.onClose,
      title: /* @__PURE__ */ __h("div", { className: "pbe-preview__title" }, /* @__PURE__ */ __h("span", { className: "pbe-mono" }, path), preview ? /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, bytes(preview.bytes)) : null),
      footer: /* @__PURE__ */ __h(__Fragment, null, props.target.canDownload ? /* @__PURE__ */ __h(Button, { onClick: save, disabled: !preview }, "下载") : null, /* @__PURE__ */ __h(Button, { type: "primary", onClick: props.onClose }, "关闭"))
    },
    error ? /* @__PURE__ */ __h(Alert, { type: "error", showIcon: true, message: "读不到这个文件", description: error }) : null,
    !error && !preview ? /* @__PURE__ */ __h(Skeleton, { active: true, paragraph: { rows: 6 } }) : null,
    preview ? /* @__PURE__ */ __h(PreviewBody, { preview }) : null
  );
}
function PreviewBody(props) {
  const { preview } = props;
  if (preview.kind === "binary") {
    return /* @__PURE__ */ __h(EmptyHint, null, `${preview.media_type}，${bytes(preview.bytes)}，不能在页面里打开。下载后用本地程序查看。`);
  }
  if (preview.kind === "image") {
    if (!preview.data_url) {
      return /* @__PURE__ */ __h(EmptyHint, null, `图片 ${bytes(preview.bytes)}，超过内联预览的上限了，下载后查看。`);
    }
    return /* @__PURE__ */ __h("img", { className: "pbe-preview__image", src: preview.data_url, alt: preview.path });
  }
  return /* @__PURE__ */ __h(__Fragment, null, preview.truncated ? /* @__PURE__ */ __h("div", { className: "pbe-preview__note" }, `只显示前 ${bytes(preview.shown_bytes)}，全文 ${bytes(preview.bytes)}——下载可以拿到完整的。`) : null, /* @__PURE__ */ __h("pre", { className: "pbe-block pbe-preview" }, preview.text || "（空文件）"));
}

// src/modules/dataset-detail.tsx
var GRADING = {
  automated: "自动判分",
  llm_judge: "LLM 判分",
  hybrid: "混合判分"
};
var NO_TASKS = [];
function gradingLabel(value) {
  if (!value) return "—";
  return GRADING[value] ?? value;
}
function kindLabel(kind) {
  if (kind === "builtin_view") return "内置视图";
  if (kind === "custom") return "自定义包";
  return kind || "—";
}
function filterSummary(spec) {
  const parts = Object.entries(spec ?? {});
  if (!parts.length) return "无（整个语料）";
  return parts.map(
    ([key, value]) => Array.isArray(value) ? `${key}（${value.length} 项）` : `${key} = ${String(value)}`
  ).join(" · ");
}
function scenarioOf(labels) {
  const scenario = labels?.scenario;
  return typeof scenario === "string" && scenario ? scenario : "—";
}
function Disclosure(props) {
  const [open, setOpen] = useState(false);
  return /* @__PURE__ */ __h("div", null, /* @__PURE__ */ __h(
    "button",
    {
      type: "button",
      className: "pbe-disclosure",
      "aria-expanded": open,
      "aria-controls": props.id,
      onClick: () => setOpen((prev) => !prev)
    },
    /* @__PURE__ */ __h("span", { className: "pbe-disclosure__label" }, props.label),
    /* @__PURE__ */ __h("span", { className: "pbe-disclosure__note" }, props.note),
    /* @__PURE__ */ __h("span", { className: "pbe-disclosure__act" }, open ? "收起" : "展开"),
    /* @__PURE__ */ __h(
      "svg",
      {
        className: "pbe-disclosure__chevron",
        width: "12",
        height: "12",
        viewBox: "0 0 12 12",
        "aria-hidden": "true",
        focusable: "false"
      },
      /* @__PURE__ */ __h("path", { d: "M4 2.5 8.5 6 4 9.5", fill: "none", stroke: "currentColor", strokeWidth: "1.6" })
    )
  ), open ? /* @__PURE__ */ __h("div", { id: props.id, style: { marginTop: "var(--spacer-8)" } }, props.children) : null);
}
function DatasetDetailModule(props) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setDetail(null);
    api.datasetDetail(props.datasetId).then((answer) => {
      if (!alive) return;
      setDetail(answer);
      setError(null);
    }).catch((err) => {
      if (alive) setError(describeError(err));
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [props.datasetId]);
  const tasks = detail?.tasks ?? NO_TASKS;
  const haystacks = useMemo(
    () => new Map(
      tasks.map((task) => [
        task.task_id,
        [task.task_id, task.name, JSON.stringify(task.labels ?? {})].join(" ").toLowerCase()
      ])
    ),
    [tasks]
  );
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return tasks;
    return tasks.filter((task) => haystacks.get(task.task_id)?.includes(needle));
  }, [tasks, haystacks, search]);
  return /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(
    PageHead,
    {
      title: detail?.name || props.datasetId,
      sub: /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("span", null, detail ? kindLabel(detail.kind) : "读取中", " · ", detail?.owner || "—", " ·", " ", tasks.length, " 题"), /* @__PURE__ */ __h("span", { className: "pbe-meta" }, /* @__PURE__ */ __h(CopyId, { value: props.datasetId, label: "数据集 id", keep: 24 }), (detail?.categories ?? []).length ? /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("span", { className: "pbe-meta__sep" }, "·"), /* @__PURE__ */ __h("span", null, detail.categories.join("、"))) : null)),
      actions: /* @__PURE__ */ __h(Button, { onClick: props.onBack }, "返回数据集列表")
    }
  ), error ? /* @__PURE__ */ __h(
    Alert,
    {
      type: "error",
      showIcon: true,
      message: error.code,
      description: error.message,
      style: { marginBottom: "var(--spacer-16)" }
    }
  ) : null, detail ? /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "这个集合"), /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, detail.description || "这个集合没有写描述。"), /* @__PURE__ */ __h("div", { className: "pbe-meta", style: { marginTop: "var(--spacer-12)" } }, /* @__PURE__ */ __h("span", null, "分类：", (detail.categories ?? []).join("、") || "未分类"), /* @__PURE__ */ __h("span", { className: "pbe-meta__sep" }, "·"), /* @__PURE__ */ __h("span", null, "筛选条件：", filterSummary(detail.filter_spec)))) : null, /* @__PURE__ */ __h("div", { className: "pbe-toolbar", style: { marginTop: "var(--spacer-16)" } }, /* @__PURE__ */ __h("span", { className: "pbe-toolbar__label" }, "题目"), /* @__PURE__ */ __h(
    Input.Search,
    {
      allowClear: true,
      "aria-label": "搜索题目",
      placeholder: "名称 / task id / 标签",
      style: { width: 280 },
      value: search,
      onChange: (event) => setSearch(event.target.value)
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-toolbar__right" }, /* @__PURE__ */ __h("span", { className: "pbe-toolbar__label" }, "共 ", shown.length, " 条", search.trim() ? `（全部 ${tasks.length}）` : ""))), /* @__PURE__ */ __h("div", { className: "pbe-table-wrap" }, /* @__PURE__ */ __h(
    Table,
    {
      className: "pbe-table",
      rowKey: "task_id",
      size: "middle",
      loading,
      dataSource: shown,
      pagination: { pageSize: 50, hideOnSinglePage: true },
      onRow: (task) => ({
        onClick: () => props.onOpenTask(task.task_id),
        tabIndex: 0,
        onKeyDown: (event) => {
          if (event.target !== event.currentTarget) return;
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            props.onOpenTask(task.task_id);
          }
        }
      }),
      locale: {
        emptyText: /* @__PURE__ */ __h(EmptyHint, null, error ? "读不到这个数据集的题目" : "没有符合搜索的题目")
      },
      columns: [
        {
          title: "题目",
          dataIndex: "name",
          render: (_, task) => /* @__PURE__ */ __h("div", null, /* @__PURE__ */ __h("div", { className: "pbe-cell-title" }, task.name || task.task_id), /* @__PURE__ */ __h("div", { className: "pbe-cell-sub pbe-mono" }, task.task_id))
        },
        {
          title: "场景",
          dataIndex: "labels",
          width: 240,
          render: (_, task) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, scenarioOf(task.labels))
        },
        {
          title: "复杂度",
          dataIndex: "complexity",
          width: 90,
          render: (_, task) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, String(task.labels?.complexity ?? "—"))
        },
        {
          title: "判分",
          dataIndex: "grading_type",
          width: 110,
          render: (value) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, gradingLabel(value))
        },
        {
          title: "超时",
          dataIndex: "timeout_seconds",
          width: 90,
          render: (value) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, value, "s")
        },
        {
          title: "附件",
          dataIndex: "attachment_count",
          width: 90,
          render: (value, task) => task.has_attachments ? /* @__PURE__ */ __h("span", { className: "pbe-pill pbe-pill--info" }, value, " 个") : /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, "—")
        }
      ]
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-table__foot" }, /* @__PURE__ */ __h("span", null, "共 ", shown.length, " 条"), /* @__PURE__ */ __h("span", null, "点一行看题干、附件与判分方式"))));
}
function DatasetTaskModule(props) {
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [preview, setPreview] = useState(null);
  useEffect(() => {
    let alive = true;
    setLoading(true);
    setDetail(null);
    api.datasetTask(props.datasetId, props.taskId).then((answer) => {
      if (!alive) return;
      setDetail(answer);
      setError(null);
    }).catch((err) => {
      if (alive) setError(describeError(err));
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [props.datasetId, props.taskId]);
  const labels = detail?.labels ?? {};
  const attachments = detail?.attachments ?? [];
  return /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(
    PageHead,
    {
      title: detail?.name || props.taskId,
      sub: /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("span", null, detail ? gradingLabel(detail.grading_type) : "读取中", " ·", " ", detail ? `${detail.timeout_seconds}s` : "—", " ·", " ", scenarioOf(labels)), /* @__PURE__ */ __h("span", { className: "pbe-meta" }, /* @__PURE__ */ __h(CopyId, { value: props.datasetId, label: "数据集", keep: 20 }), /* @__PURE__ */ __h("span", { className: "pbe-meta__sep" }, "/"), /* @__PURE__ */ __h(CopyId, { value: props.taskId, label: "task id", keep: 28 }))),
      actions: /* @__PURE__ */ __h(Button, { onClick: props.onBack }, "返回题目清单")
    }
  ), error ? /* @__PURE__ */ __h(
    Alert,
    {
      type: "error",
      showIcon: true,
      message: error.code,
      description: error.message,
      style: { marginBottom: "var(--spacer-16)" }
    }
  ) : null, detail?.unreadable ? /* @__PURE__ */ __h(
    Alert,
    {
      type: "warning",
      showIcon: true,
      message: "这道题的 markdown 解析不了",
      description: `${detail.unreadable}。标签还在，题干读不出来；改好文件后刷新本页。`,
      style: { marginBottom: "var(--spacer-16)" }
    }
  ) : null, /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "题干"), loading && !detail ? /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, "读取中…") : /* @__PURE__ */ __h("pre", { className: "pbe-block pbe-prompt" }, detail?.prompt || "（这道题没有记录题干）"), detail?.expected_behavior ? /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("div", { style: { height: "var(--spacer-16)" } }), /* @__PURE__ */ __h(SectionTitle, null, "期望行为"), /* @__PURE__ */ __h("pre", { className: "pbe-block pbe-prompt" }, detail.expected_behavior)) : null), /* @__PURE__ */ __h("div", { style: { marginTop: "var(--spacer-16)" } }, /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h("div", { style: { display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "var(--spacer-12)" } }, /* @__PURE__ */ __h(SectionTitle, null, "判分规则"), /* @__PURE__ */ __h(
    Button,
    {
      size: "small",
      onClick: () => setPreview({ kind: "source", path: `${props.taskId}.md`, canDownload: false })
    },
    "看题目 markdown"
  )), /* @__PURE__ */ __h("div", { className: "pbe-facts" }, /* @__PURE__ */ __h(Fact, { label: "判分方式", value: gradingLabel(detail?.grading_type) }), /* @__PURE__ */ __h(Fact, { label: "权重", value: weightsOf(detail?.grading_weights) })), detail?.grading_criteria?.length ? /* @__PURE__ */ __h("div", { style: { marginTop: "var(--spacer-12)" } }, /* @__PURE__ */ __h("div", { className: "pbe-cell-sub", style: { marginBottom: "var(--spacer-6)" } }, "判据"), /* @__PURE__ */ __h(
    "ul",
    {
      style: {
        margin: 0,
        paddingLeft: "var(--spacer-20)",
        color: "var(--text-default)",
        lineHeight: 1.7
      }
    },
    detail.grading_criteria.map((item) => /* @__PURE__ */ __h("li", { key: item }, item))
  )) : null, detail?.llm_judge_rubric ? /* @__PURE__ */ __h("div", { style: { marginTop: "var(--spacer-12)" } }, /* @__PURE__ */ __h(
    Disclosure,
    {
      id: "task-rubric",
      label: "判分细则",
      note: `${detail.llm_judge_rubric.length} 字`
    },
    /* @__PURE__ */ __h("pre", { className: "pbe-block", style: { maxHeight: 340, overflowY: "auto" } }, detail.llm_judge_rubric)
  )) : null, detail?.has_automated_checks ? /* @__PURE__ */ __h("div", { className: "pbe-cell-sub", style: { marginTop: "var(--spacer-12)" } }, "这道题另有一段自动检查脚本，跑在判分器里。脚本里写着这道题的答案，所以不在页面上出现——上面这两块是它按什么标准给分。") : null)), /* @__PURE__ */ __h("div", { className: "pbe-grid", style: { marginTop: "var(--spacer-16)" } }, /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "标签与属性"), /* @__PURE__ */ __h("div", { className: "pbe-facts" }, /* @__PURE__ */ __h(Fact, { label: "超时", value: detail ? `${detail.timeout_seconds} 秒` : "—" }), /* @__PURE__ */ __h(Fact, { label: "场景", value: scenarioOf(labels) }), /* @__PURE__ */ __h(Fact, { label: "复杂度", value: String(labels.complexity ?? "—") }), /* @__PURE__ */ __h(Fact, { label: "环境", value: String(labels.environment ?? "—") }), /* @__PURE__ */ __h(Fact, { label: "能力", value: labelList(labels.capabilities) }), /* @__PURE__ */ __h(Fact, { label: "模态", value: modalityOf(labels.modality) }))), /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "题目带的文件"), attachments.length ? /* @__PURE__ */ __h("div", { className: "pbe-rows" }, attachments.map((item) => /* @__PURE__ */ __h(
    "button",
    {
      key: item.path,
      type: "button",
      className: "pbe-row pbe-row--file",
      disabled: !item.present,
      onClick: () => setPreview({ kind: "fixture", path: item.path, canDownload: true })
    },
    /* @__PURE__ */ __h("span", { className: "pbe-row__grow pbe-mono" }, item.path),
    item.present ? null : /* @__PURE__ */ __h(StatusPill, { tone: "err", label: "文件缺失" }),
    /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, item.size === null ? "—" : bytes(item.size)),
    item.present ? /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, "预览") : null
  ))) : /* @__PURE__ */ __h(EmptyHint, null, "这道题不带文件，只需要读题干。"))), preview ? /* @__PURE__ */ __h(
    PreviewModal,
    {
      source: { kind: "dataset", datasetId: props.datasetId, taskId: props.taskId },
      target: preview,
      onClose: () => setPreview(null)
    }
  ) : null);
}
function weightsOf(weights) {
  const parts = Object.entries(weights ?? {});
  if (!parts.length) return "—";
  const names = { automated: "自动", llm_judge: "LLM", hybrid: "混合" };
  return parts.map(([key, value]) => `${names[key] ?? key} ${Math.round(Number(value) * 100)}%`).join(" · ");
}
function labelList(value) {
  return Array.isArray(value) ? value.join("、") || "—" : typeof value === "string" ? value : "—";
}
function modalityOf(value) {
  if (typeof value === "string") return value || "—";
  if (value && typeof value === "object") {
    const record = value;
    const type = typeof record.type === "string" ? record.type : "";
    const channels = labelList(record.channels);
    return [type, channels === "—" ? "" : channels].filter(Boolean).join(" · ") || "—";
  }
  return "—";
}

// src/modules/jobs.tsx
var PAGE_SIZE = 20;
var ORDERABLE = /* @__PURE__ */ new Set(["queued", "scheduled"]);
var FINISHED = /* @__PURE__ */ new Set(["finished", "failed", "canceled"]);
function progressOf(job) {
  const total = Math.max(0, Number(job.task_count) || 0);
  const finished = Math.max(0, Number(job.tasks_finished) || 0);
  return { finished, total, ratio: total ? Math.min(1, finished / total) : 0 };
}
function scoreTone(score) {
  if (score === null || score === void 0) return "";
  if (score >= 0.8) return " pbe-score--ok";
  if (score < 0.5) return " pbe-score--low";
  return "";
}
var RANK_LIVE = 0;
var RANK_WAITING = 1;
var RANK_ENDED = 2;
function rankOf(job) {
  if (job.status === "running") return RANK_LIVE;
  if (ORDERABLE.has(job.status)) return RANK_WAITING;
  return RANK_ENDED;
}
function byReadingOrder(a, b) {
  const rank = rankOf(a) - rankOf(b);
  if (rank !== 0) return rank;
  if (rankOf(a) !== RANK_ENDED) {
    return (Number(a.queue_pos) || 0) - (Number(b.queue_pos) || 0);
  }
  return String(b.created_at).localeCompare(String(a.created_at));
}
function JobsModule(props) {
  const feedback = useFeedback();
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState("");
  const stats = useMemo(() => {
    const running = props.jobs.filter((job) => job.status === "running").length;
    const waiting = props.jobs.filter((job) => ORDERABLE.has(job.status)).length;
    const done = props.jobs.filter((job) => job.status === "finished").length;
    const scored = props.jobs.map((job) => job.score).filter((score) => typeof score === "number");
    const mean = scored.length ? scored.reduce((sum, value) => sum + value, 0) / scored.length : null;
    return { running, waiting, done, mean, scored: scored.length };
  }, [props.jobs]);
  const visible = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return props.jobs.filter((job) => {
      if (filter === "running" && job.status !== "running") return false;
      if (filter === "waiting" && !ORDERABLE.has(job.status)) return false;
      if (filter === "done" && !FINISHED.has(job.status)) return false;
      if (!needle) return true;
      return [job.purpose, job.product, job.job_id, job.submitter, job.acp_url].join(" ").toLowerCase().includes(needle);
    }).sort(byReadingOrder);
  }, [props.jobs, filter, search]);
  const paged = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return visible.slice(start, start + PAGE_SIZE);
  }, [visible, page]);
  const canReorder = (job) => ORDERABLE.has(job.status) && (!props.subject || job.submitter === props.subject);
  async function reorder(job, target) {
    setBusy(job.job_id);
    try {
      await api.reorder(job.job_id, { target });
      props.onRefresh();
    } catch (error) {
      const info = describeError(error);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy("");
    }
  }
  async function cancel(job) {
    setBusy(job.job_id);
    try {
      await api.cancel(job.job_id, "dashboard");
      feedback.message.success("已取消");
      props.onRefresh();
    } catch (error) {
      const info = describeError(error);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy("");
    }
  }
  const icon = icons();
  const Play = icon.PlayCircleOutlined;
  const Clock = icon.ClockCircleOutlined;
  const Check = icon.CheckCircleOutlined;
  const Gauge = icon.DashboardOutlined;
  const columns = [
    {
      title: "状态",
      dataIndex: "status",
      width: 124,
      render: (_, job) => {
        const meta = jobStatus(job.status);
        return /* @__PURE__ */ __h("div", null, /* @__PURE__ */ __h(StatusPill, { tone: meta.tone, label: meta.label }), ORDERABLE.has(job.status) && job.queue_pos !== null ? /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, "队列 #", Number(job.queue_pos).toFixed(1)) : null);
      }
    },
    {
      title: "评测",
      dataIndex: "purpose",
      render: (_, job) => /* @__PURE__ */ __h("div", { style: { minWidth: 0 } }, /* @__PURE__ */ __h("div", { className: "pbe-cell-title" }, job.purpose || "（未命名）"), /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, job.product || "—", " · ", job.job_id))
    },
    {
      title: "题目",
      dataIndex: "task_count",
      width: 156,
      render: (_, job) => {
        const progress = progressOf(job);
        return /* @__PURE__ */ __h("div", null, /* @__PURE__ */ __h("div", { className: "pbe-cell-sub", style: { marginBottom: 4 } }, /* @__PURE__ */ __h("span", { className: "pbe-mono" }, progress.finished, " / ", progress.total || "?"), job.tasks_failed ? ` · ${job.tasks_failed} 失败` : ""), /* @__PURE__ */ __h(
          Progress,
          {
            percent: Math.round(progress.ratio * 100),
            size: "small",
            showInfo: false,
            status: job.tasks_failed ? "exception" : job.status === "running" ? "active" : "normal"
          }
        ));
      }
    },
    {
      title: "分数",
      dataIndex: "score",
      width: 92,
      render: (_, job) => /* @__PURE__ */ __h("span", { className: `pbe-figure${scoreTone(job.score)}` }, job.score === null || job.score === void 0 ? "—" : fixed(job.score))
    },
    {
      title: "提交人",
      dataIndex: "submitter",
      width: 104,
      render: (value) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, value || "—")
    },
    {
      title: "时间",
      dataIndex: "created_at",
      width: 156,
      render: (_, job) => /* @__PURE__ */ __h("div", null, /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, stamp(job.created_at)), job.finished_at ? /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, "耗时 ", duration(secondsBetween(job))) : job.not_before ? /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, "起跑 ", stamp(job.not_before)) : null)
    },
    {
      title: "操作",
      dataIndex: "job_id",
      width: 150,
      render: (_, job) => {
        const disabled = !canReorder(job) || busy === job.job_id;
        const why = !ORDERABLE.has(job.status) ? "已经不在队列里了" : props.subject && job.submitter !== props.subject ? "只能调自己提交的作业" : "";
        return /* @__PURE__ */ __h("div", { style: { display: "flex", gap: 4 }, onClick: (event) => event.stopPropagation() }, /* @__PURE__ */ __h(Tooltip, { title: why || "上移" }, /* @__PURE__ */ __h(
          Button,
          {
            size: "small",
            type: "text",
            "aria-label": "上移",
            disabled,
            onClick: () => reorder(job, "up")
          },
          "↑"
        )), /* @__PURE__ */ __h(Tooltip, { title: why || "下移" }, /* @__PURE__ */ __h(
          Button,
          {
            size: "small",
            type: "text",
            "aria-label": "下移",
            disabled,
            onClick: () => reorder(job, "down")
          },
          "↓"
        )), /* @__PURE__ */ __h(Tooltip, { title: "打开报告" }, /* @__PURE__ */ __h(Button, { size: "small", type: "text", "aria-label": "打开报告", onClick: () => props.onOpen(job.job_id) }, "报告")), ORDERABLE.has(job.status) || job.status === "running" ? /* @__PURE__ */ __h(
          Popconfirm,
          {
            title: "取消这次评测？",
            description: job.status === "running" ? "运行中的会话会被停掉，已跑完的题保留。" : "排队中的作业会被移出队列。",
            okText: "取消作业",
            cancelText: "先不取消",
            onConfirm: () => cancel(job)
          },
          /* @__PURE__ */ __h(Tooltip, { title: "取消" }, /* @__PURE__ */ __h(Button, { size: "small", type: "text", danger: true, "aria-label": "取消", disabled }, "取消"))
        ) : null);
      }
    }
  ];
  return /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(
    PageHead,
    {
      title: "评测",
      sub: "一次提交一行。点任意一行打开报告；行内能看到题目进度和平均分。",
      actions: /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(Tooltip, { title: "重新拉取列表" }, /* @__PURE__ */ __h(Button, { "aria-label": "刷新", onClick: props.onRefresh, loading: props.loading }, "刷新")), /* @__PURE__ */ __h(Button, { type: "primary", onClick: props.onNew }, "新建评测"))
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-metrics" }, /* @__PURE__ */ __h(
    MetricItem,
    {
      icon: Play ? /* @__PURE__ */ __h(Play, null) : null,
      title: "运行中",
      figure: stats.running,
      note: stats.running ? "占着并发槽" : "当前空闲"
    }
  ), /* @__PURE__ */ __h(
    MetricItem,
    {
      icon: Clock ? /* @__PURE__ */ __h(Clock, null) : null,
      title: "等待中",
      figure: stats.waiting,
      note: stats.waiting ? "含排队与待起跑" : "队列为空"
    }
  ), /* @__PURE__ */ __h(
    MetricItem,
    {
      icon: Gauge ? /* @__PURE__ */ __h(Gauge, null) : null,
      title: "已完成",
      figure: stats.done,
      note: `平均分 ${stats.mean === null ? "—" : fixed(stats.mean)}${stats.scored ? ` · ${stats.scored} 次计分` : ""}`
    }
  )), /* @__PURE__ */ __h("div", { className: "pbe-toolbar" }, /* @__PURE__ */ __h("span", { className: "pbe-toolbar__label" }, "筛选"), /* @__PURE__ */ __h(
    Segmented,
    {
      value: filter,
      onChange: (value) => {
        setFilter(value);
        setPage(1);
      },
      options: [
        { value: "all", label: `全部 ${props.jobs.length}` },
        { value: "running", label: "运行中" },
        { value: "waiting", label: "等待中" },
        { value: "done", label: "已结束" }
      ]
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-toolbar__right" }, /* @__PURE__ */ __h(
    Input.Search,
    {
      allowClear: true,
      placeholder: "按目的、产品、提交人、job id 搜索",
      style: { width: 260 },
      value: search,
      onChange: (event) => {
        setSearch(event.target.value);
        setPage(1);
      }
    }
  ))), /* @__PURE__ */ __h("div", { className: "pbe-table-wrap" }, /* @__PURE__ */ __h(
    Table,
    {
      className: "pbe-table",
      rowKey: "job_id",
      size: "middle",
      loading: props.loading && !props.jobs.length,
      columns,
      dataSource: paged,
      pagination: false,
      onRow: (job) => ({ onClick: () => props.onOpen(job.job_id) }),
      locale: {
        emptyText: /* @__PURE__ */ __h(EmptyHint, null, "还没有评测。点右上角「新建评测」提交一次，或检查「配置」里的服务地址。")
      }
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-table__foot" }, /* @__PURE__ */ __h("span", null, "共 ", visible.length, " 条"), /* @__PURE__ */ __h(
    Pagination,
    {
      size: "small",
      current: page,
      pageSize: PAGE_SIZE,
      total: visible.length,
      showSizeChanger: false,
      onChange: (next) => setPage(next),
      hideOnSinglePage: true
    }
  ))), /* @__PURE__ */ __h("div", { className: "pbe-toolbar", style: { marginTop: "var(--spacer-16)" } }, /* @__PURE__ */ __h("span", { className: "pbe-toolbar__label" }, "「等待中」才可调序；「已结束」才有报告。分数显示「—」表示没有可计分的题，不等于 0 分。"), /* @__PURE__ */ __h("div", { className: "pbe-toolbar__right" }, /* @__PURE__ */ __h(Check, { style: { color: "var(--status-success-default)" } }), /* @__PURE__ */ __h("span", { className: "pbe-toolbar__label" }, "列表会在运行中自动刷新"))));
}
function MetricItem(props) {
  return /* @__PURE__ */ __h("div", { className: "pbe-panel pbe-metric" }, /* @__PURE__ */ __h("span", { className: "pbe-tile", "aria-hidden": "true" }, props.icon), /* @__PURE__ */ __h("div", { className: "pbe-metric__body" }, /* @__PURE__ */ __h("div", { className: "pbe-metric__title" }, props.title), /* @__PURE__ */ __h("div", { className: "pbe-metric__desc" }, /* @__PURE__ */ __h("span", { className: "pbe-figure" }, props.figure), /* @__PURE__ */ __h("span", null, props.note))));
}
function secondsBetween(job) {
  if (!job.started_at || !job.finished_at) return null;
  const start = Date.parse(job.started_at);
  const end = Date.parse(job.finished_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, (end - start) / 1e3);
}

// src/modules/new-job.tsx
function NewJobModal(props) {
  const feedback = useFeedback();
  const [acpUrl, setAcpUrl] = useState("");
  const [product, setProduct] = useState("");
  const [purpose, setPurpose] = useState("");
  const [envText, setEnvText] = useState("");
  const [datasets, setDatasets] = useState([]);
  const [categories, setCategories] = useState([]);
  const [kind, setKind] = useState("immediate");
  const [range, setRange] = useState(null);
  const [catalog, setCatalog] = useState({
    datasets: null,
    categories: null
  });
  const [resolved, setResolved] = useState(null);
  const [resolving, setResolving] = useState(false);
  const [busy, setBusy] = useState(false);
  const fingerprint = useMemo(() => parseFingerprint(envText), [envText]);
  useEffect(() => {
    if (!props.open) return;
    let alive = true;
    Promise.all([api.datasets(), api.categories()]).then(([list, cats]) => {
      if (alive) setCatalog({ datasets: list, categories: cats });
    }).catch((err) => {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    });
    return () => {
      alive = false;
    };
  }, [props.open]);
  const selection = useMemo(() => ({ categories, datasets }), [categories, datasets]);
  useEffect(() => {
    if (!props.open) return;
    if (!categories.length && !datasets.length) {
      setResolved(null);
      return;
    }
    let alive = true;
    setResolving(true);
    api.resolve(selection).then((result) => {
      if (alive) setResolved(result);
    }).catch(() => {
      if (alive) setResolved(null);
    }).finally(() => {
      if (alive) setResolving(false);
    });
    return () => {
      alive = false;
    };
  }, [categories, datasets, props.open]);
  async function submit() {
    if (fingerprint.problems.length) {
      feedback.message.error(fingerprint.problems[0]);
      return;
    }
    const window2 = { kind };
    if (kind === "custom") {
      if (!range || !range[0] || !range[1]) {
        feedback.message.error("自定义区间要选开始和结束时间");
        return;
      }
      window2.not_before = toIso(range[0]);
      window2.not_after = toIso(range[1]);
    }
    setBusy(true);
    try {
      const body = {
        acp_url: acpUrl.trim(),
        product: product.trim(),
        purpose: purpose.trim(),
        selector: { categories, datasets },
        window: window2
      };
      if (fingerprint.count) body.env_fingerprint = fingerprint.pairs;
      const job = await api.submit(body);
      feedback.message.success(`已提交 ${job.job_id}`);
      api.learnIdentity(job.job_id).then((result) => result.subject && props.onIdentity(result.subject)).catch(() => void 0);
      setAcpUrl("");
      setProduct("");
      setPurpose("");
      setEnvText("");
      setCategories([]);
      setDatasets([]);
      setKind("immediate");
      setRange(null);
      props.onSubmitted(job);
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy(false);
    }
  }
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const serviceTz = "Asia/Shanghai";
  return /* @__PURE__ */ __h(
    Modal,
    {
      open: props.open,
      title: "新建评测",
      width: 680,
      onCancel: props.onClose,
      onOk: submit,
      okText: "提交评测",
      cancelText: "取消",
      confirmLoading: busy,
      destroyOnClose: true,
      footer: /* @__PURE__ */ __h("div", { style: { display: "flex", justifyContent: "flex-end", gap: "var(--spacer-8)" } }, /* @__PURE__ */ __h(Button, { onClick: props.onClose }, "取消"), /* @__PURE__ */ __h(
        Button,
        {
          type: "primary",
          loading: busy,
          disabled: !acpUrl.trim() || !product.trim() || !purpose.trim(),
          onClick: submit
        },
        "提交评测"
      ))
    },
    /* @__PURE__ */ __h(Fieldset, { title: "目标" }, /* @__PURE__ */ __h(Field, { label: "ACP 地址", hint: "被测 agent 的 ACP 端点，http:// 或 https:// 开头" }, /* @__PURE__ */ __h(
      Input,
      {
        value: acpUrl,
        onChange: (event) => setAcpUrl(event.target.value),
        placeholder: "http://127.0.0.1:8472/acp"
      }
    )), /* @__PURE__ */ __h(Field, { label: "产品" }, /* @__PURE__ */ __h(
      Input,
      {
        value: product,
        onChange: (event) => setProduct(event.target.value),
        placeholder: "被评测的是什么，如 QwenPaw 2.3"
      }
    )), /* @__PURE__ */ __h(Field, { label: "目的", hint: "一周后回看，能解释这条曲线为什么跳的就是这两栏" }, /* @__PURE__ */ __h(
      Input,
      {
        value: purpose,
        onChange: (event) => setPurpose(event.target.value),
        placeholder: "如 夜间冒烟 / 回归 / 发版前"
      }
    )), /* @__PURE__ */ __h(
      Field,
      {
        label: "环境指纹",
        hint: (
          // A count under a warning would read as "these will be stored",
          // which is the opposite of what the warning says.
          fingerprint.problems.length ? "改好上面那几行才能提交" : fingerprint.count ? `存进报告：${shownKeys(fingerprint.keys)}` : "每行一个 key=value，如 model=gpt-6-sol。留空就不带——报告会写明这次提交没有带指纹。服务上限 4 KB"
        )
      },
      /* @__PURE__ */ __h(
        Input.TextArea,
        {
          rows: 3,
          value: envText,
          onChange: (event) => setEnvText(event.target.value),
          placeholder: "model=gpt-6-sol\nagent_id=pawbench_eval\nbuild=2.2.2"
        }
      ),
      fingerprint.problems.length ? /* @__PURE__ */ __h(
        Alert,
        {
          type: "warning",
          showIcon: true,
          style: { marginTop: "var(--spacer-8)" },
          message: shownProblems(fingerprint.problems)
        }
      ) : null
    )),
    /* @__PURE__ */ __h(Fieldset, { title: "选题" }, /* @__PURE__ */ __h(Field, { label: "分类", hint: "选中一个分类等于选中它下面所有数据集" }, /* @__PURE__ */ __h(
      Select,
      {
        mode: "multiple",
        allowClear: true,
        style: { width: "100%" },
        value: categories,
        onChange: (value) => setCategories(value),
        placeholder: "按分类整组选",
        options: (catalog.categories?.categories ?? []).map((item) => ({
          value: item.name,
          label: item.name
        }))
      }
    )), /* @__PURE__ */ __h(Field, { label: "数据集" }, /* @__PURE__ */ __h(
      Select,
      {
        mode: "multiple",
        allowClear: true,
        style: { width: "100%" },
        value: datasets,
        onChange: (value) => setDatasets(value),
        placeholder: "选单个数据集",
        options: (catalog.datasets?.datasets ?? []).map((item) => ({
          value: item.id,
          label: `${item.name || item.id}（${item.task_count} 题）`
        }))
      }
    )), /* @__PURE__ */ __h(Field, { label: "题量" }, /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, resolving ? /* @__PURE__ */ __h(Spin, { size: "small" }) : resolved ? /* @__PURE__ */ __h(__Fragment, null, "将跑 ", /* @__PURE__ */ __h(Figure, { value: resolved.task_count }), " 道题", resolved.duplicates_removed ? ` · 去重 ${resolved.duplicates_removed} 道` : "", resolved.unknown_ids?.length ? ` · ${resolved.unknown_ids.length} 个选择项不存在` : "") : "选完分类或数据集后，这里显示服务算出来的题量"))),
    /* @__PURE__ */ __h(Fieldset, { title: "窗口" }, /* @__PURE__ */ __h(Field, { label: "何时跑" }, /* @__PURE__ */ __h(
      Segmented,
      {
        value: kind,
        onChange: (value) => setKind(value),
        options: [
          { value: "immediate", label: "立即" },
          { value: "night", label: "夜间固定窗" },
          { value: "custom", label: "自定义区间" }
        ]
      }
    )), kind === "custom" ? /* @__PURE__ */ __h(Field, { label: "区间", hint: `按本机时区选择（${tz}）` }, /* @__PURE__ */ __h(
      DatePicker.RangePicker,
      {
        showTime: true,
        style: { width: "100%" },
        value: range,
        onChange: (value) => setRange(value)
      }
    )) : null, kind !== "immediate" ? /* @__PURE__ */ __h(
      Alert,
      {
        type: "info",
        showIcon: true,
        message: `服务在 ${serviceTz} 判断窗口`,
        description: kind === "night" ? `夜间固定窗由服务配置决定，本机时区是 ${tz}；两者不同的话，以服务为准。` : `你按 ${tz} 选的时间会换算成 UTC 发给服务，报告里显示的是 UTC。`
      }
    ) : null)
  );
}
function parseFingerprint(text) {
  const pairs = /* @__PURE__ */ Object.create(null);
  const problems = [];
  text.split("\n").forEach((raw, index) => {
    const line = raw.trim();
    if (!line) return;
    const cut = line.indexOf("=");
    const key = cut < 0 ? "" : line.slice(0, cut).trim();
    if (!key) {
      problems.push(`第 ${index + 1} 行不是 key=value`);
      return;
    }
    if (Object.prototype.hasOwnProperty.call(pairs, key)) {
      problems.push(`第 ${index + 1} 行的 ${key} 与前面重复`);
      return;
    }
    pairs[key] = line.slice(cut + 1).trim();
  });
  const keys = Object.keys(pairs);
  return { pairs, keys, count: keys.length, problems };
}
function shownProblems(problems, limit = 3) {
  if (problems.length <= limit) return problems.join("；");
  return `${problems.slice(0, limit).join("；")}；另有 ${problems.length - limit} 行`;
}
function shownKeys(keys, limit = 3) {
  if (keys.length <= limit) return keys.join("、");
  return `${keys.slice(0, limit).join("、")} 等 ${keys.length} 项`;
}
function toIso(value) {
  if (value && typeof value.toISOString === "function") return value.toISOString();
  if (value && typeof value.toDate === "function") return value.toDate().toISOString();
  return new Date(value).toISOString();
}

// src/ui/trace.tsx
var SIZES = [10, 20, 50];
function clock(at) {
  const text = String(at ?? "");
  return text.includes("T") ? text.slice(11, 19) : text;
}
function num(value) {
  return Number(value ?? 0).toLocaleString("en-US");
}
function Trace(props) {
  const page = props.page;
  const size = page?.size ?? 10;
  const voice = page?.voice ?? "all";
  const beats = page?.beats ?? [];
  function go(next) {
    props.onPage(next, size, voice);
  }
  return /* @__PURE__ */ __h("div", { className: "pbe-trace" }, /* @__PURE__ */ __h("div", { className: "pbe-trace__bar" }, /* @__PURE__ */ __h(
    Segmented,
    {
      size: "small",
      value: voice,
      onChange: (value) => props.onPage(1, size, value),
      options: BeatFilters.map((item) => ({
        value: item.value,
        label: `${item.label} ${num(page?.counts[item.value])}`
      }))
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-trace__nav" }, /* @__PURE__ */ __h("span", { className: "pbe-trace__pos" }, page && page.total_beats ? `第 ${num((page.page - 1) * size + 1)}–${num((page.page - 1) * size + beats.length)} 步 · 共 ${num(page.total_beats)} 步` : page ? "没有可显示的步骤" : "读取中", page && page.damaged_events ? ` · ${num(page.damaged_events)} 行读不出` : ""), /* @__PURE__ */ __h(
    Segmented,
    {
      size: "small",
      value: size,
      onChange: (value) => props.onPage(1, Number(value), voice),
      options: SIZES.map((value) => ({ value, label: `${value}/页` }))
    }
  ), /* @__PURE__ */ __h(Button, { size: "small", disabled: !page || page.page === 1 || props.loading, onClick: () => go(1) }, "回到开头"), /* @__PURE__ */ __h(Button, { size: "small", disabled: !page || page.page <= 1 || props.loading, onClick: () => go(page.page - 1) }, "上一页"), /* @__PURE__ */ __h(
    Button,
    {
      size: "small",
      type: "primary",
      ghost: true,
      disabled: !page || page.next_page === null || props.loading,
      onClick: () => page?.next_page !== null && page && go(page.next_page)
    },
    "下一页"
  ))), props.error ? /* @__PURE__ */ __h("div", { className: "pbe-trace__error" }, props.error) : null, /* @__PURE__ */ __h("div", { className: "pbe-trace__scroll", "aria-busy": props.loading }, page?.transcript_state === "absent" ? /* @__PURE__ */ __h("div", { className: "pbe-trace__quiet" }, "这次运行没有留下轨迹。可能是 agent 一句没说就退出了，也可能是轨迹文件在运行后被清理掉了。") : page?.transcript_state === "unreadable" ? /* @__PURE__ */ __h("div", { className: "pbe-trace__quiet" }, "轨迹文件在，但读不出来。", " ", /* @__PURE__ */ __h("span", { className: "pbe-mono" }, "transcript.jsonl"), " 可能被占用或权限变了。") : beats.length === 0 ? /* @__PURE__ */ __h("div", { className: "pbe-trace__quiet" }, page && page.total_beats ? "这一页没有符合筛选的步骤。" : "这次运行没有可显示的步骤。") : beats.map((beat) => /* @__PURE__ */ __h(
    BeatRow,
    {
      key: beat.key,
      beat,
      opened: props.opened[beat.index],
      onOpen: () => props.onOpen(beat.index)
    }
  ))), page && page.next_page !== null ? /* @__PURE__ */ __h("div", { className: "pbe-trace__foot" }, /* @__PURE__ */ __h("span", { className: "pbe-trace__pos" }, "还有 ", num(page.total_beats - (page.page - 1) * size - beats.length), " 步"), /* @__PURE__ */ __h(Button, { size: "small", onClick: () => page.next_page !== null && go(page.next_page) }, "继续看下一页")) : null);
}
function BeatRow(props) {
  const beat = props.beat;
  if (beat.voice === "system") return /* @__PURE__ */ __h(SystemRow, { beat });
  if (beat.voice === "tool")
    return /* @__PURE__ */ __h(ToolRow, { beat, opened: props.opened, onOpen: props.onOpen });
  if (beat.voice === "plan") return /* @__PURE__ */ __h(PlanRow, { beat });
  if (beat.voice === "thought")
    return /* @__PURE__ */ __h(ThoughtRow, { beat, opened: props.opened, onOpen: props.onOpen });
  return /* @__PURE__ */ __h(SpeechRow, { beat, opened: props.opened, onOpen: props.onOpen });
}
function Rail(props) {
  return /* @__PURE__ */ __h("span", { className: `pbe-beat__rail pbe-beat__rail--${props.voice}`, "aria-hidden": "true" }, /* @__PURE__ */ __h("span", { className: "pbe-beat__dot" }));
}
function Meta(props) {
  const beat = props.beat;
  return /* @__PURE__ */ __h("div", { className: "pbe-beat__meta" }, /* @__PURE__ */ __h("span", { className: "pbe-beat__who" }, beat.label), /* @__PURE__ */ __h("span", { className: "pbe-mono" }, clock(beat.at)), beat.events > 1 && beat.voice !== "tool" ? /* @__PURE__ */ __h("span", null, beat.events, " 段") : null, props.extra, props.more ? /* @__PURE__ */ __h("span", { className: "pbe-beat__more-slot" }, props.more) : null);
}
function MoreButton(props) {
  const loading = Boolean(props.opened?.loading);
  const open = Boolean(props.opened) && !loading;
  const label = loading ? "读取完整内容…" : open ? "收起" : props.collapsedLabel;
  return /* @__PURE__ */ __h(
    "button",
    {
      type: "button",
      className: `pbe-beat__more${open ? " pbe-beat__more--open" : ""}`,
      "aria-expanded": open,
      disabled: loading,
      onClick: props.onOpen
    },
    label
  );
}
function SpeechRow(props) {
  const beat = props.beat;
  const open = Boolean(props.opened);
  const full = props.opened?.content;
  const text = open && full ? full.text : beat.text;
  const expandable = Boolean(beat.text_truncated || open);
  return /* @__PURE__ */ __h("div", { className: `pbe-beat pbe-beat--${beat.voice}` }, /* @__PURE__ */ __h(Rail, { voice: beat.voice }), /* @__PURE__ */ __h("div", { className: "pbe-beat__body" }, /* @__PURE__ */ __h(
    Meta,
    {
      beat,
      extra: beat.chars ? /* @__PURE__ */ __h("span", null, num(beat.chars), " 字符") : null,
      more: expandable ? /* @__PURE__ */ __h(
        MoreButton,
        {
          opened: props.opened,
          onOpen: props.onOpen,
          collapsedLabel: "展开完整内容"
        }
      ) : null
    }
  ), text ? /* @__PURE__ */ __h("div", { className: "pbe-speech" }, text) : /* @__PURE__ */ __h("div", { className: "pbe-beat__quiet" }, "这一条只有长度，没有正文（", num(beat.chars), " 字符）。")));
}
function ThoughtRow(props) {
  const beat = props.beat;
  const open = Boolean(props.opened);
  const full = props.opened?.content;
  const text = open && full ? full.text : beat.text;
  return /* @__PURE__ */ __h("div", { className: "pbe-beat pbe-beat--thought" }, /* @__PURE__ */ __h(Rail, { voice: beat.voice }), /* @__PURE__ */ __h("div", { className: "pbe-beat__body" }, /* @__PURE__ */ __h(
    Meta,
    {
      beat,
      more: /* @__PURE__ */ __h(
        MoreButton,
        {
          opened: props.opened,
          onOpen: props.onOpen,
          collapsedLabel: `${beat.text_truncated ? "展开完整内容" : "展开"} · ${num(beat.chars)} 字符`
        }
      )
    }
  ), /* @__PURE__ */ __h("div", { className: `pbe-thought${open ? " pbe-thought--open" : ""}` }, text || "（这次运行没有记录思考内容）")));
}
function ToolRow(props) {
  const beat = props.beat;
  const open = Boolean(props.opened);
  const full = props.opened?.content;
  const sourceArgs = open && full ? full.args : beat.args;
  const args = Object.entries(sourceArgs ?? {}).map(([key, value]) => {
    const lines = String(value).split("\n");
    const long = lines.length > 1 || value.length > 80;
    return {
      key,
      value: String(value),
      // A heredoc collapsed into one nowrap line reads as a run-on sentence.
      // On an opened card the value is already full, so it wraps in full too.
      preview: lines.length > 1 ? `${lines[0]} …（还有 ${lines.length - 1} 行）` : String(value),
      long
    };
  });
  const shown = open ? args : args.slice(0, 3);
  const hidden = args.length - shown.length;
  const output = open && full ? full.output : beat.output;
  const failed = beat.status === "failed" || beat.status === "error";
  const tone = failed ? "err" : beat.status === "completed" ? "ok" : "warn";
  const label = beat.status === "completed" ? "完成" : failed ? "失败" : beat.status || "进行中";
  const clipped = args.some((arg) => arg.long) || output.split("\n").length > 4 || output.length > 260;
  const expandable = args.length > 3 || clipped || beat.output_truncated || beat.text_truncated;
  return /* @__PURE__ */ __h("div", { className: "pbe-beat pbe-beat--tool" }, /* @__PURE__ */ __h(Rail, { voice: beat.voice }), /* @__PURE__ */ __h("div", { className: "pbe-beat__body" }, /* @__PURE__ */ __h(
    Meta,
    {
      beat,
      more: expandable || open ? /* @__PURE__ */ __h(
        MoreButton,
        {
          opened: props.opened,
          onOpen: props.onOpen,
          collapsedLabel: hidden > 0 ? `展开其余 ${hidden} 个参数${clipped ? "与完整结果" : ""}` : "展开完整内容"
        }
      ) : null
    }
  ), /* @__PURE__ */ __h("div", { className: `pbe-tool${failed ? " pbe-tool--failed" : ""}` }, /* @__PURE__ */ __h("div", { className: "pbe-tool__head" }, /* @__PURE__ */ __h("span", { className: "pbe-tool__title" }, beat.tool || beat.name || "工具调用"), beat.name && beat.name !== beat.tool ? /* @__PURE__ */ __h("span", { className: "pbe-tool__name pbe-mono" }, beat.name) : null, /* @__PURE__ */ __h(StatusPill, { tone, label }), beat.result_chars ? /* @__PURE__ */ __h("span", { className: "pbe-tool__size" }, num(beat.result_chars), " 字符") : null), shown.length ? /* @__PURE__ */ __h("div", { className: "pbe-tool__args" }, shown.map((arg) => /* @__PURE__ */ __h("div", { className: "pbe-tool__arg", key: arg.key }, /* @__PURE__ */ __h("span", { className: "pbe-tool__key" }, arg.key), /* @__PURE__ */ __h(
    "span",
    {
      className: `pbe-tool__value pbe-mono${open ? " pbe-tool__value--wrap" : ""}`,
      title: open ? arg.value : void 0
    },
    open ? arg.value : arg.preview
  )))) : null, output ? /* @__PURE__ */ __h("div", { className: `pbe-tool__out${open ? " pbe-tool__out--open" : ""}` }, /* @__PURE__ */ __h("span", { className: "pbe-tool__out-label" }, "结果"), /* @__PURE__ */ __h("pre", { className: "pbe-tool__out-text" }, output)) : null)));
}
function PlanRow(props) {
  const beat = props.beat;
  const lines = (beat.text || "").split("\n").filter(Boolean);
  return /* @__PURE__ */ __h("div", { className: "pbe-beat pbe-beat--plan" }, /* @__PURE__ */ __h(Rail, { voice: beat.voice }), /* @__PURE__ */ __h("div", { className: "pbe-beat__body" }, /* @__PURE__ */ __h(Meta, { beat, extra: beat.steps ? /* @__PURE__ */ __h("span", null, beat.steps, " 步") : null }), lines.length ? /* @__PURE__ */ __h("ul", { className: "pbe-plan" }, lines.map((line, index) => {
    const matched = /^\[([a-z_]+)\]\s*(.*)$/.exec(line);
    const status = matched ? matched[1] : "pending";
    const text = matched ? matched[2] : line;
    return /* @__PURE__ */ __h("li", { className: `pbe-plan__item pbe-plan__item--${status}`, key: `${index}-${text}` }, /* @__PURE__ */ __h("span", { className: "pbe-plan__mark", "aria-hidden": "true" }, status === "completed" ? "✓" : status === "in_progress" ? "▸" : "·"), /* @__PURE__ */ __h("span", null, text));
  })) : /* @__PURE__ */ __h("div", { className: "pbe-beat__quiet" }, "计划更新了 ", beat.steps, " 步，但这次没有带内容。")));
}
function SystemRow(props) {
  const beat = props.beat;
  const [open, setOpen] = useState(false);
  const kinds = Array.from(new Set(beat.kinds));
  const summary = kinds.map((kind) => kind).join(" / ");
  return /* @__PURE__ */ __h("div", { className: "pbe-beat pbe-beat--system" }, /* @__PURE__ */ __h(Rail, { voice: beat.voice }), /* @__PURE__ */ __h("div", { className: "pbe-beat__body" }, /* @__PURE__ */ __h("button", { type: "button", className: "pbe-system", "aria-expanded": open, onClick: () => setOpen(!open) }, /* @__PURE__ */ __h("span", { className: "pbe-mono" }, clock(beat.at)), /* @__PURE__ */ __h("span", null, beat.events, " 条", summary || "系统", "事件"), /* @__PURE__ */ __h("span", { className: "pbe-system__act" }, open ? "收起" : "看是哪几条")), open ? /* @__PURE__ */ __h("ul", { className: "pbe-system__list" }, beat.kinds.map((kind, index) => /* @__PURE__ */ __h("li", { key: `${index}-${kind}`, className: "pbe-mono" }, kind))) : null));
}

// src/modules/report.tsx
var FORMATS = [
  { value: "md", label: "Markdown", hint: "一页读完，适合贴进 issue 或 wiki" },
  { value: "html", label: "HTML", hint: "同内容带样式，适合发给不装工具的人" },
  { value: "json", label: "JSON", hint: "原始字段，适合二次处理" },
  { value: "zip", label: "ZIP", hint: "报告 + 产物原文件" }
];
function isBad(task) {
  return task.status !== "finished" || Boolean(task.failure_reason);
}
function lowScore(task) {
  return typeof task.score === "number" && task.score < 0.8;
}
function ReportModule(props) {
  const feedback = useFeedback();
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("overview");
  const [openTask, setOpenTask] = useState(null);
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [format, setFormat] = useState("md");
  const [exporting, setExporting] = useState(false);
  const [lastExport, setLastExport] = useState(
    null
  );
  useEffect(() => {
    let alive = true;
    setLoading(true);
    api.detail(props.jobId).then((next) => {
      if (!alive) return;
      setDetail(next);
      setError(null);
    }).catch((err) => {
      if (!alive) return;
      setError(describeError(err));
    }).finally(() => {
      if (alive) setLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [props.jobId]);
  const tasks = detail?.tasks ?? [];
  const shown = useMemo(() => {
    const needle = search.trim().toLowerCase();
    return tasks.filter((task) => {
      if (filter === "bad" && !isBad(task)) return false;
      if (filter === "low" && !lowScore(task)) return false;
      if (filter === "unscored" && typeof task.score === "number") return false;
      if (!needle) return true;
      return [task.task_id, task.name, task.labels?.scenario, task.trace_id, task.session_id].join(" ").toLowerCase().includes(needle);
    });
  }, [tasks, filter, search]);
  async function generate() {
    setExporting(true);
    try {
      const link = await api.report(props.jobId, format);
      setLastExport({ filename: link.filename, size: link.size, url: link.url });
      window.open(link.url, "_blank", "noopener");
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setExporting(false);
    }
  }
  const scores = tasks.map((task) => task.score).filter((value) => typeof value === "number");
  const high = scores.length ? Math.max(...scores) : null;
  const low = scores.length ? Math.min(...scores) : null;
  const summary = typeof detail?.score === "number" ? null : detail?.score ?? null;
  const mean = typeof detail?.score === "number" ? detail.score : summary?.mean ?? null;
  const scoreCount = summary?.count ?? scores.length;
  const linkFor = `${window.location.origin}${window.location.pathname}?job=${props.jobId}`;
  const progress = detail?.progress ?? {};
  const byStatus = progress.by_status ?? {};
  const statusRows = Object.entries(byStatus);
  const totalTasks = progress.total ?? tasks.length;
  const finishedTasks = byStatus.finished ?? tasks.filter((task) => task.status === "finished").length;
  const failedTasks = byStatus.failed ?? tasks.filter((task) => task.status === "failed").length;
  return /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(
    PageHead,
    {
      title: detail?.purpose || "报告",
      sub: /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("span", null, detail?.product || "—", " · ", detail?.submitter || "—"), /* @__PURE__ */ __h("span", { className: "pbe-meta" }, /* @__PURE__ */ __h(CopyId, { value: props.jobId, label: "job id", keep: 20 }), /* @__PURE__ */ __h("span", { className: "pbe-meta__sep" }, "·"), /* @__PURE__ */ __h(
        StatusPill,
        {
          tone: detail ? jobStatus(detail.status).tone : "muted",
          label: detail ? jobStatus(detail.status).label : "读取中"
        }
      ), /* @__PURE__ */ __h("span", { className: "pbe-meta__sep" }, "·"), /* @__PURE__ */ __h(CopyId, { value: linkFor, label: "报告链接", keep: 30 }))),
      actions: /* @__PURE__ */ __h(Button, { onClick: props.onBack }, "返回列表")
    }
  ), error ? /* @__PURE__ */ __h(
    Alert,
    {
      type: "error",
      showIcon: true,
      message: error.code,
      description: error.message,
      style: { marginBottom: "var(--spacer-16)" }
    }
  ) : null, detail?.error ? /* @__PURE__ */ __h(
    Alert,
    {
      type: "warning",
      showIcon: true,
      message: "这次运行没有跑完",
      description: detail.error,
      style: { marginBottom: "var(--spacer-16)" }
    }
  ) : null, /* @__PURE__ */ __h(Panel, { pad: false }, /* @__PURE__ */ __h("div", { style: { padding: "var(--spacer-20) var(--spacer-24)" } }, /* @__PURE__ */ __h("div", { className: "pbe-scoreboard" }, /* @__PURE__ */ __h(Cell, { label: "总分", value: mean === null ? "—" : fixed(mean), note: detail?.score ? `计分 ${scoreCount} 题` : void 0 }), /* @__PURE__ */ __h(
    Cell,
    {
      label: "完成",
      value: `${finishedTasks} / ${totalTasks}`,
      note: failedTasks ? `${failedTasks} 失败` : "无失败"
    }
  ), /* @__PURE__ */ __h(Cell, { label: "分数区间", value: high === null ? "—" : `${fixed(low)} – ${fixed(high)}`, note: `${scores.length} 题计分` }), /* @__PURE__ */ __h(Cell, { label: "耗时", value: duration(secondsBetween2(detail)), note: stamp(detail?.started_at) })))), /* @__PURE__ */ __h(
    Tabs,
    {
      activeKey: tab,
      onChange: setTab,
      items: [
        {
          key: "overview",
          label: "总览",
          children: /* @__PURE__ */ __h("div", { className: "pbe-grid", style: { marginTop: "var(--spacer-16)" } }, /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "总分与状态分布"), /* @__PURE__ */ __h("div", { style: { display: "flex", alignItems: "center", gap: "var(--spacer-24)" } }, /* @__PURE__ */ __h(
            Progress,
            {
              type: "dashboard",
              size: 132,
              percent: mean === null ? 0 : Math.round(mean * 100),
              format: () => mean === null ? "—" : fixed(mean)
            }
          ), /* @__PURE__ */ __h("div", { className: "pbe-rows", style: { flex: 1 } }, /* @__PURE__ */ __h(Row, { label: "计分题", value: String(progress.scored ?? scores.length) }), /* @__PURE__ */ __h(Row, { label: "没计分的", value: String(Math.max(0, totalTasks - (progress.scored ?? 0))) }), /* @__PURE__ */ __h(
            Row,
            {
              label: "最高 / 最低",
              value: high === null ? "—" : `${fixed(high)} / ${fixed(low)}`
            }
          ), /* @__PURE__ */ __h(Row, { label: "生成时间", value: stamp(detail?.generated_at) }))), statusRows.length ? /* @__PURE__ */ __h("div", { className: "pbe-rows", style: { marginTop: "var(--spacer-12)" } }, statusRows.map(([key, value]) => /* @__PURE__ */ __h(Row, { key, label: jobStatus(key).label, value: `${value} 题` }))) : null), /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "切片"), /* @__PURE__ */ __h(Slices, { title: "能力", data: detail?.slices?.capability }), /* @__PURE__ */ __h(Slices, { title: "场景", data: detail?.slices?.scenario }), /* @__PURE__ */ __h(Slices, { title: "复杂度", data: detail?.slices?.complexity })), /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "数据来源"), (detail?.sources ?? []).length ? /* @__PURE__ */ __h("div", { className: "pbe-rows" }, detail.sources.map((source) => /* @__PURE__ */ __h(
            Row,
            {
              key: source.dataset_id,
              label: String(source.name || source.dataset_id),
              value: `${source.task_count} 题`
            }
          ))) : /* @__PURE__ */ __h(EmptyHint, null, "这次运行没有记录数据来源")), /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "运行配置"), /* @__PURE__ */ __h("div", { className: "pbe-facts" }, /* @__PURE__ */ __h(Fact, { label: "ACP 地址", value: /* @__PURE__ */ __h("span", { className: "pbe-mono" }, detail?.acp_url) }), /* @__PURE__ */ __h(
            Fact,
            {
              label: "窗口",
              value: detail ? `${detail.window.kind}${detail.window.start ? ` · ${stamp(detail.window.start)}` : ""}` : "—"
            }
          ), /* @__PURE__ */ __h(Fact, { label: "提交时间", value: stamp(detail?.created_at) }), /* @__PURE__ */ __h(Fact, { label: "结束时间", value: stamp(detail?.finished_at) }))), /* @__PURE__ */ __h(Panel, { spanAll: true }, /* @__PURE__ */ __h(SectionTitle, null, "环境指纹"), /* @__PURE__ */ __h("div", { className: "pbe-block", style: { maxHeight: 240 } }, json(detail?.env_fingerprint ?? "这次提交没有带指纹"))))
        },
        {
          key: "tasks",
          label: `题目 ${tasks.length}`,
          children: /* @__PURE__ */ __h("div", { style: { marginTop: "var(--spacer-16)" } }, /* @__PURE__ */ __h("div", { className: "pbe-toolbar" }, /* @__PURE__ */ __h("span", { className: "pbe-toolbar__label" }, "筛选"), /* @__PURE__ */ __h(
            Segmented,
            {
              value: filter,
              onChange: (value) => setFilter(value),
              options: [
                { value: "all", label: `全部 ${tasks.length}` },
                { value: "bad", label: `异常 ${tasks.filter(isBad).length}` },
                { value: "low", label: `低分 ${tasks.filter(lowScore).length}` },
                { value: "unscored", label: "未计分" }
              ]
            }
          ), /* @__PURE__ */ __h("div", { className: "pbe-toolbar__right" }, /* @__PURE__ */ __h(
            Input.Search,
            {
              allowClear: true,
              placeholder: "题目名 / task id / trace id",
              style: { width: 260 },
              value: search,
              onChange: (event) => setSearch(event.target.value)
            }
          ))), /* @__PURE__ */ __h("div", { className: "pbe-table-wrap" }, /* @__PURE__ */ __h(
            Table,
            {
              className: "pbe-table",
              rowKey: (task) => `${task.task_id}-${task.attempt}`,
              size: "middle",
              loading,
              dataSource: shown,
              pagination: false,
              onRow: (task) => ({ onClick: () => setOpenTask(task) }),
              locale: { emptyText: /* @__PURE__ */ __h(EmptyHint, null, "没有符合筛选的题目") },
              columns: taskColumns()
            }
          ), /* @__PURE__ */ __h("div", { className: "pbe-table__foot" }, /* @__PURE__ */ __h("span", null, "共 ", shown.length, " 条"), /* @__PURE__ */ __h("span", null, "点一行看题干、判据与轨迹"))))
        },
        {
          key: "export",
          label: "导出",
          children: /* @__PURE__ */ __h("div", { className: "pbe-grid", style: { marginTop: "var(--spacer-16)" } }, /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "生成报告"), /* @__PURE__ */ __h(
            Radio.Group,
            {
              value: format,
              onChange: (event) => setFormat(event.target.value),
              style: { display: "flex", flexDirection: "column", gap: "var(--spacer-12)" }
            },
            FORMATS.map((item) => /* @__PURE__ */ __h(Radio, { key: item.value, value: item.value }, /* @__PURE__ */ __h("span", null, item.label), /* @__PURE__ */ __h("span", { className: "pbe-cell-sub", style: { marginLeft: 8 } }, item.hint)))
          ), /* @__PURE__ */ __h("div", { style: { marginTop: "var(--spacer-20)", display: "flex", gap: "var(--spacer-8)" } }, /* @__PURE__ */ __h(Button, { type: "primary", loading: exporting, onClick: generate }, "生成并打开"), /* @__PURE__ */ __h(Tooltip, { title: "submissions/*.json 的形状，排行榜直接吃得下" }, /* @__PURE__ */ __h(Button, { onClick: () => void saveSubmissions(props.jobId) }, "另存 submissions JSON")))), /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "刚刚生成的"), lastExport ? /* @__PURE__ */ __h("div", { className: "pbe-facts" }, /* @__PURE__ */ __h(Fact, { label: "文件", value: /* @__PURE__ */ __h("span", { className: "pbe-mono" }, lastExport.filename) }), /* @__PURE__ */ __h(Fact, { label: "大小", value: bytes(lastExport.size) }), /* @__PURE__ */ __h(
            Fact,
            {
              label: "链接",
              value: /* @__PURE__ */ __h(Button, { type: "link", style: { padding: 0 }, onClick: () => window.open(lastExport.url, "_blank", "noopener") }, "再打开一次")
            }
          ), /* @__PURE__ */ __h(
            Fact,
            {
              label: "保存到本地",
              value: /* @__PURE__ */ __h(
                Button,
                {
                  type: "link",
                  style: { padding: 0 },
                  onClick: () => {
                    void downloadToFile(props.jobId, lastExport.filename);
                  }
                },
                "通过代理下载"
              )
            }
          )) : /* @__PURE__ */ __h(EmptyHint, null, "还没有生成。选一种格式，点左边「生成并打开」。")))
        }
      ]
    }
  ), openTask ? /* @__PURE__ */ __h(TaskDialog, { jobId: props.jobId, task: openTask, onClose: () => setOpenTask(null) }) : null);
}
async function saveSubmissions(jobId) {
  const payload = await api.results(jobId);
  saveBlob(
    new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }),
    `${jobId}.json`
  );
}
async function downloadToFile(jobId, filename) {
  await download(`/v1/reports/${jobId}/${encodeURIComponent(filename)}`, filename);
}
function Cell(props) {
  return /* @__PURE__ */ __h("div", { className: "pbe-scoreboard__cell" }, /* @__PURE__ */ __h("div", { className: "pbe-scoreboard__label" }, props.label), /* @__PURE__ */ __h("div", { className: "pbe-scoreboard__value" }, props.value), props.note ? /* @__PURE__ */ __h("div", { className: "pbe-scoreboard__label" }, props.note) : null);
}
function Row(props) {
  return /* @__PURE__ */ __h("div", { className: "pbe-row" }, /* @__PURE__ */ __h("span", { className: "pbe-row__grow" }, props.label), /* @__PURE__ */ __h("span", { className: "pbe-mono" }, props.value));
}
function Slices(props) {
  const entries = Object.entries(props.data ?? {});
  if (!entries.length) {
    return /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, "没有", props.title, "切片");
  }
  return /* @__PURE__ */ __h("div", { style: { marginBottom: "var(--spacer-12)" } }, /* @__PURE__ */ __h("div", { className: "pbe-cell-sub", style: { marginBottom: "var(--spacer-8)" } }, props.title), entries.map(([name, score]) => /* @__PURE__ */ __h("div", { key: name, style: { marginBottom: "var(--spacer-8)" } }, /* @__PURE__ */ __h("div", { style: { display: "flex", justifyContent: "space-between" } }, /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, name), /* @__PURE__ */ __h("span", { className: "pbe-mono" }, fixed(score))), /* @__PURE__ */ __h(Progress, { percent: Math.round(Number(score) * 100), size: "small", showInfo: false }))));
}
function taskColumns() {
  return [
    {
      title: "题目",
      dataIndex: "name",
      render: (_, task) => /* @__PURE__ */ __h("div", null, /* @__PURE__ */ __h("div", { className: "pbe-cell-title" }, task.name || task.task_id), /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, task.task_id, task.attempt > 1 ? ` · 第 ${task.attempt} 次尝试` : ""))
    },
    {
      title: "标签",
      dataIndex: "labels",
      width: 220,
      render: (_, task) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, String(task.labels?.scenario ?? "—"))
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 140,
      render: (_, task) => {
        const meta = taskStatus(task.status, task.failure_reason);
        return /* @__PURE__ */ __h(StatusPill, { tone: meta.tone, label: meta.label });
      }
    },
    {
      title: "分数",
      dataIndex: "score",
      width: 84,
      render: (_, task) => /* @__PURE__ */ __h(Figure, { value: typeof task.score === "number" ? fixed(task.score) : "—" })
    },
    {
      title: "耗时",
      dataIndex: "duration_s",
      width: 96,
      render: (_, task) => /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, duration(task.duration_s))
    },
    {
      title: "trace_id",
      dataIndex: "trace_id",
      width: 148,
      render: (_, task) => /* @__PURE__ */ __h(CopyId, { value: task.trace_id, label: "trace_id", keep: 12 })
    }
  ];
}
function TaskDialog(props) {
  const [detail, setDetail] = useState(props.task);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState(null);
  const [tracePage, setTracePage] = useState(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState("");
  const [opened, setOpened] = useState({});
  const [nav, setNav] = useState({ page: 1, size: 10, voice: "all" });
  useEffect(() => {
    let alive = true;
    api.taskDetail(props.jobId, props.task.task_id, props.task.attempt).then((next) => {
      if (alive) setDetail(next);
    }).catch((err) => {
      if (alive) setError(describeError(err).message);
    });
    return () => {
      alive = false;
    };
  }, [props.jobId, props.task.task_id, props.task.attempt]);
  useEffect(() => {
    let alive = true;
    setTraceLoading(true);
    setOpened({});
    api.beats(
      props.jobId,
      props.task.task_id,
      props.task.attempt,
      nav.page,
      nav.size,
      nav.voice
    ).then((next) => {
      if (!alive) return;
      setTracePage(next);
      setTraceError("");
    }).catch((err) => {
      if (alive) setTraceError(describeError(err).message);
    }).finally(() => {
      if (alive) setTraceLoading(false);
    });
    return () => {
      alive = false;
    };
  }, [props.jobId, props.task.task_id, props.task.attempt, nav.page, nav.size, nav.voice]);
  function goPage(page, size, voice) {
    setNav({ page, size, voice });
  }
  function toggleBeat(index) {
    const current = opened[index];
    if (current) {
      const next = { ...opened };
      delete next[index];
      setOpened(next);
      return;
    }
    const voice = tracePage?.voice ?? "all";
    setOpened({
      ...opened,
      [index]: { content: null, loading: true }
    });
    api.beatContent(props.jobId, props.task.task_id, props.task.attempt, index, voice).then((content) => {
      setOpened((prev) => ({ ...prev, [index]: { content, loading: false } }));
    }).catch(() => {
      setOpened((prev) => ({ ...prev, [index]: { content: null, loading: false } }));
      setTraceError("读不到这一段的完整内容。");
    });
  }
  const breakdown = Object.entries(detail.automated_breakdown ?? {});
  const attachments = detail.attachments ?? [];
  const notes = detail.judge_notes;
  const judgeText = notes === null || notes === void 0 || typeof notes === "object" && !Object.keys(notes).length ? "" : json(notes);
  const meta = taskStatus(detail.status, detail.failure_reason);
  return /* @__PURE__ */ __h(
    Modal,
    {
      open: true,
      width: 1040,
      onCancel: props.onClose,
      footer: /* @__PURE__ */ __h(Button, { onClick: props.onClose }, "关闭"),
      title: /* @__PURE__ */ __h("div", { style: { display: "flex", alignItems: "center", gap: "var(--spacer-12)" } }, /* @__PURE__ */ __h("span", null, detail.name || detail.task_id), /* @__PURE__ */ __h(StatusPill, { tone: meta.tone, label: meta.label }), /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, typeof detail.score === "number" ? `得分 ${fixed(detail.score)}` : "未计分"))
    },
    error ? /* @__PURE__ */ __h(Alert, { type: "error", showIcon: true, message: "读不到这一题", description: error }) : null,
    /* @__PURE__ */ __h(SectionTitle, null, "题干"),
    /* @__PURE__ */ __h("pre", { className: "pbe-block pbe-prompt" }, detail.prompt || "（这次运行没有记录题干）"),
    attachments.length ? /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("div", { style: { height: "var(--spacer-20)" } }), /* @__PURE__ */ __h(SectionTitle, null, "附件"), /* @__PURE__ */ __h("div", { className: "pbe-rows" }, attachments.map((item) => /* @__PURE__ */ __h(
      FileRow,
      {
        key: item.path,
        path: item.path,
        size: item.size,
        note: item.copy === "attempt" ? "运行时副本" : void 0,
        onOpen: () => setPreview({ kind: "attachments", path: item.path, canDownload: true })
      }
    )))) : null,
    /* @__PURE__ */ __h("div", { style: { height: "var(--spacer-20)" } }),
    /* @__PURE__ */ __h(SectionTitle, null, "这次执行"),
    /* @__PURE__ */ __h("div", { className: "pbe-facts" }, /* @__PURE__ */ __h(Fact, { label: "判分方式", value: detail.grading_type || "—" }), /* @__PURE__ */ __h(Fact, { label: "耗时", value: duration(detail.duration_s) }), /* @__PURE__ */ __h(Fact, { label: "协议写回 / 带外", value: `${detail.protocol_written} / ${detail.out_of_band_count}` }), /* @__PURE__ */ __h(
      Fact,
      {
        label: "自报模型",
        value: (detail.subject_model_reported ?? []).join("、") || "—"
      }
    ), /* @__PURE__ */ __h(Fact, { label: "解析自", value: (detail.resolved_from ?? []).join("、") || "—" }), /* @__PURE__ */ __h(Fact, { label: "trace_id", value: /* @__PURE__ */ __h(CopyId, { value: detail.trace_id, label: "trace_id", keep: 16 }) }), /* @__PURE__ */ __h(Fact, { label: "session_id", value: /* @__PURE__ */ __h(CopyId, { value: detail.session_id, label: "session_id", keep: 24 }) })),
    breakdown.length ? /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("div", { style: { height: "var(--spacer-20)" } }), /* @__PURE__ */ __h(SectionTitle, null, "判据逐项"), /* @__PURE__ */ __h("div", { className: "pbe-rows" }, breakdown.map(([name, value]) => /* @__PURE__ */ __h("div", { className: "pbe-row", key: name }, /* @__PURE__ */ __h("span", { className: "pbe-row__grow" }, name), /* @__PURE__ */ __h(
      StatusPill,
      {
        tone: Number(value) >= 1 ? "ok" : Number(value) > 0 ? "warn" : "err",
        label: fixed(value)
      }
    ))))) : null,
    /* @__PURE__ */ __h("div", { style: { height: "var(--spacer-20)" } }),
    /* @__PURE__ */ __h(SectionTitle, null, "产物"),
    detail.artifacts.length ? /* @__PURE__ */ __h("div", { className: "pbe-rows" }, detail.artifacts.map((artifact) => /* @__PURE__ */ __h(
      FileRow,
      {
        key: artifact.path,
        path: artifact.path,
        size: artifact.size,
        digest: artifact.sha256,
        onOpen: () => setPreview({ kind: "artifacts", path: artifact.path, canDownload: true })
      }
    ))) : /* @__PURE__ */ __h(EmptyHint, null, "这次没有产物"),
    detail.rubric_excerpt || judgeText ? /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("div", { style: { height: "var(--spacer-20)" } }), /* @__PURE__ */ __h(SectionTitle, null, "评分依据"), detail.rubric_excerpt ? /* @__PURE__ */ __h("pre", { className: "pbe-block" }, detail.rubric_excerpt) : null, judgeText ? /* @__PURE__ */ __h("pre", { className: "pbe-block", style: { marginTop: "var(--spacer-8)" } }, judgeText) : null) : null,
    /* @__PURE__ */ __h("div", { style: { height: "var(--spacer-20)" } }),
    /* @__PURE__ */ __h(SectionTitle, null, "轨迹"),
    /* @__PURE__ */ __h(
      Trace,
      {
        jobId: props.jobId,
        taskId: detail.task_id,
        attempt: detail.attempt,
        page: tracePage,
        loading: traceLoading,
        error: traceError,
        opened,
        onPage: goPage,
        onOpen: toggleBeat
      }
    ),
    preview ? /* @__PURE__ */ __h(
      PreviewModal,
      {
        source: {
          kind: "job",
          jobId: props.jobId,
          taskId: detail.task_id,
          attempt: detail.attempt
        },
        target: preview,
        onClose: () => setPreview(null)
      }
    ) : null
  );
}
function FileRow(props) {
  const body = /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h("span", { className: "pbe-row__grow pbe-mono" }, props.path), props.note ? /* @__PURE__ */ __h("span", { className: "pbe-pill pbe-pill--muted" }, props.note) : null, /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, props.size === null ? "—" : bytes(props.size)), props.digest ? /* @__PURE__ */ __h(Tooltip, { title: props.digest }, /* @__PURE__ */ __h("span", { className: "pbe-cell-sub pbe-mono" }, props.digest.slice(0, 12))) : null, props.onOpen ? /* @__PURE__ */ __h("span", { className: "pbe-cell-sub" }, "预览") : null);
  if (!props.onOpen) {
    return /* @__PURE__ */ __h("div", { className: "pbe-row" }, body);
  }
  return /* @__PURE__ */ __h("button", { type: "button", className: "pbe-row pbe-row--file", onClick: props.onOpen }, body);
}
function secondsBetween2(detail) {
  if (!detail?.started_at || !detail.finished_at) return null;
  const start = Date.parse(detail.started_at);
  const end = Date.parse(detail.finished_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, (end - start) / 1e3);
}

// src/modules/settings.tsx
var SOURCE_TEXT = {
  file: "来自本机保存的配置",
  env: "来自环境变量（PAWBENCH_EVAL_*）",
  none: "还没有配置"
};
function SettingsModule(props) {
  const feedback = useFeedback();
  const [baseUrl, setBaseUrl] = useState("");
  const [token, setToken] = useState("");
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState("");
  const [probe, setProbe] = useState(null);
  const [probeError, setProbeError] = useState("");
  useEffect(() => {
    const config2 = props.config;
    if (!config2) return;
    setBaseUrl(config2.base_url || "");
    setSubject(config2.subject || "");
  }, [props.config]);
  async function save(thenProbe) {
    setBusy(thenProbe ? "save" : "save");
    try {
      const body = {
        base_url: baseUrl.trim(),
        subject: subject.trim()
      };
      if (token.trim()) body.token = token.trim();
      const saved = await api.saveConfig(body);
      props.onSaved(saved);
      setToken("");
      feedback.message.success("已保存");
      if (thenProbe) await runProbe();
    } catch (err) {
      const info = describeError(err);
      feedback.message.error(`${info.code}：${info.message}`);
    } finally {
      setBusy("");
    }
  }
  async function runProbe() {
    setBusy("probe");
    setProbeError("");
    try {
      const result = await api.probe();
      setProbe(result);
    } catch (err) {
      const info = describeError(err);
      setProbe(null);
      setProbeError(`${info.code}：${info.message}`);
    } finally {
      setBusy("");
    }
  }
  const config = props.config;
  return /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(
    PageHead,
    {
      title: "配置",
      sub: "页面通过本插件后端访问评测服务，token 只在后端保存，浏览器里始终没有它。",
      actions: /* @__PURE__ */ __h(__Fragment, null, /* @__PURE__ */ __h(Button, { onClick: runProbe, loading: busy === "probe" }, "只探测"), /* @__PURE__ */ __h(Button, { type: "primary", onClick: () => void save(true), loading: busy === "save" }, "保存并探测"))
    }
  ), /* @__PURE__ */ __h("div", { className: "pbe-grid" }, /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "服务连接"), /* @__PURE__ */ __h(Field, { label: "服务地址", hint: "评测服务的根地址，页面会调到它下面的 /v1/*" }, /* @__PURE__ */ __h(
    Input,
    {
      value: baseUrl,
      onChange: (event) => setBaseUrl(event.target.value),
      placeholder: "http://127.0.0.1:8471"
    }
  )), /* @__PURE__ */ __h(
    Field,
    {
      label: "访问 token",
      hint: config?.has_token ? `已保存 ${config.token_hint}；留空表示不改，填新值会替换` : "还没有 token。在服务端用 auth CLI 铸造一个，粘贴到这里。"
    },
    /* @__PURE__ */ __h(
      Input.Password,
      {
        value: token,
        onChange: (event) => setToken(event.target.value),
        placeholder: config?.has_token ? "••••••••（留空不改）" : "粘贴 token"
      }
    )
  ), /* @__PURE__ */ __h(Field, { label: "身份", hint: "服务用它判断某一行是不是你的；提交过一次后会自动学到" }, /* @__PURE__ */ __h(
    Input,
    {
      value: subject,
      onChange: (event) => setSubject(event.target.value),
      placeholder: "你的 allowlist subject"
    }
  )), probeError ? /* @__PURE__ */ __h(Alert, { type: "error", showIcon: true, message: "探测失败", description: probeError }) : null), /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "服务状态"), probe ? /* @__PURE__ */ __h("div", { className: "pbe-facts" }, /* @__PURE__ */ __h(
    Fact,
    {
      label: "可达",
      value: probe.reachable ? "是" : "否"
    }
  ), /* @__PURE__ */ __h(Fact, { label: "被认可", value: probe.authorized ? "是" : "否" }), /* @__PURE__ */ __h(Fact, { label: "说明", value: String(probe.detail || "—") }), /* @__PURE__ */ __h(Fact, { label: "配置来源", value: SOURCE_TEXT[config?.source ?? "none"] ?? config?.source ?? "—" })) : /* @__PURE__ */ __h("div", { className: "pbe-facts" }, /* @__PURE__ */ __h(Fact, { label: "配置来源", value: SOURCE_TEXT[config?.source ?? "none"] ?? config?.source ?? "—" }), /* @__PURE__ */ __h(Fact, { label: "地址", value: config?.base_url || "还没填" }), /* @__PURE__ */ __h(Fact, { label: "token", value: config?.has_token ? `已保存 ${config.token_hint}` : "还没有" }), /* @__PURE__ */ __h(Fact, { label: "身份", value: config?.subject || "还没学到" })), /* @__PURE__ */ __h("div", { className: "pbe-cell-sub", style: { marginTop: "var(--spacer-16)" } }, "探测会打服务的 /healthz：先看能不能连上，再看 token 认不认，最后报服务自己的版本。")), /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "报告默认值"), /* @__PURE__ */ __h(Fieldset, { title: "" }, /* @__PURE__ */ __h(Field, { label: "导出格式" }, /* @__PURE__ */ __h(
    Segmented,
    {
      value: props.format,
      onChange: (value) => props.onFormat(value),
      options: [
        { value: "md", label: "Markdown" },
        { value: "html", label: "HTML" },
        { value: "json", label: "JSON" },
        { value: "zip", label: "ZIP" }
      ]
    }
  ))), /* @__PURE__ */ __h("div", { className: "pbe-cell-sub" }, "只影响导出面板一开始选中的格式，存在这台浏览器里。")), /* @__PURE__ */ __h(Panel, null, /* @__PURE__ */ __h(SectionTitle, null, "关于 token"), /* @__PURE__ */ __h("div", { className: "pbe-cell-sub", style: { lineHeight: 1.8 } }, "页面调的是 ", /* @__PURE__ */ __h("span", { className: "pbe-mono" }, "/api/pawbench-eval/v1/…"), "，插件后端在转发时加上", /* @__PURE__ */ __h("span", { className: "pbe-mono" }, " Authorization: Bearer …"), "。所以：", /* @__PURE__ */ __h("br", null), "· 浏览器里没有 token 的副本，同事来屏幕共享也看不到；", /* @__PURE__ */ __h("br", null), "· 换机器要重新填一次，因为它跟着这台机器的插件目录走；", /* @__PURE__ */ __h("br", null), "· 轮换 token 之后，页面学到的提交人身份会作废，第一次提交时重新学。"))));
}

// src/shell.tsx
var FORMAT_KEY = "pawbench-eval.format";
function readStored(key, allowed, fallback) {
  try {
    const value = window.localStorage.getItem(key);
    return value && allowed.includes(value) ? value : fallback;
  } catch {
    return fallback;
  }
}
function store(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
  }
}
function Shell() {
  const boot = useMemo(() => new URLSearchParams(window.location.search), []);
  const [view, setView] = useState(() => boot.get("dataset") ? "datasets" : "jobs");
  const [jobId, setJobId] = useState(() => boot.get("job") ?? "");
  const [datasetId, setDatasetId] = useState(() => boot.get("dataset") ?? "");
  const [taskId, setTaskId] = useState(
    () => boot.get("job") || !boot.get("dataset") ? "" : boot.get("task") ?? ""
  );
  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [jobsError, setJobsError] = useState(null);
  const [config, setConfig] = useState(null);
  const [bootError, setBootError] = useState("");
  const [newOpen, setNewOpen] = useState(false);
  const [format, setFormat] = useState(
    () => readStored(FORMAT_KEY, ["md", "html", "json", "zip"], "md")
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
    api.config().then(setConfig).catch((err) => {
      const info = describeError(err);
      setBootError(`${info.code}：${info.message}`);
    });
    void refreshJobs();
  }, [refreshJobs]);
  const live = useMemo(
    () => jobs.some((job) => job.status === "running" || job.status === "queued" || job.status === "scheduled"),
    [jobs]
  );
  useEffect(() => {
    if (!live) return;
    const timer = window.setInterval(() => void refreshJobs(), 5e3);
    return () => window.clearInterval(timer);
  }, [live, refreshJobs]);
  const setQuery = useCallback((next) => {
    const url = new URL(window.location.href);
    for (const [key, value] of Object.entries(next)) {
      if (value) url.searchParams.set(key, value);
      else url.searchParams.delete(key);
    }
    window.history.replaceState({}, "", url.toString());
  }, []);
  const openReport = useCallback(
    (id) => {
      setView("jobs");
      setJobId(id);
      setDatasetId("");
      setTaskId("");
      setQuery({ job: id, dataset: "", task: "" });
    },
    [setQuery]
  );
  const backToList = useCallback(() => {
    setJobId("");
    setDatasetId("");
    setTaskId("");
    setQuery({ job: "", dataset: "", task: "" });
  }, [setQuery]);
  const openDataset = useCallback(
    (id) => {
      setView("datasets");
      setDatasetId(id);
      setTaskId("");
      setQuery({ job: "", dataset: id, task: "" });
    },
    [setQuery]
  );
  const openDatasetTask = useCallback(
    (id) => {
      setTaskId(id);
      setQuery({ task: id });
    },
    [setQuery]
  );
  const backToDatasets = useCallback(() => {
    setDatasetId("");
    setTaskId("");
    setQuery({ dataset: "", task: "" });
  }, [setQuery]);
  const backToDataset = useCallback(() => {
    setTaskId("");
    setQuery({ task: "" });
  }, [setQuery]);
  const surface = jobId ? "jobs" : datasetId ? "datasets" : view;
  const running = jobs.filter((job) => job.status === "running").length;
  const icon = icons();
  const Flask = icon.ExperimentOutlined;
  const Database = icon.DatabaseOutlined;
  const Setting = icon.SettingOutlined;
  const Reload = icon.ReloadOutlined;
  const nav = [
    { key: "jobs", label: "评测", count: running || null, glyph: Flask ? /* @__PURE__ */ __h(Flask, null) : null },
    { key: "datasets", label: "数据集", count: null, glyph: Database ? /* @__PURE__ */ __h(Database, null) : null },
    { key: "settings", label: "配置", count: null, glyph: Setting ? /* @__PURE__ */ __h(Setting, null) : null }
  ];
  return /* @__PURE__ */ __h(DesignScope, { ConfigProvider, className: "pbe-root" }, /* @__PURE__ */ __h(App, null, /* @__PURE__ */ __h("div", { className: "pbe-shell" }, /* @__PURE__ */ __h("aside", { className: "pbe-rail" }, /* @__PURE__ */ __h("div", { className: "pbe-rail__brand" }, /* @__PURE__ */ __h("span", { "aria-hidden": "true" }, "🧪"), /* @__PURE__ */ __h("span", null, "PawBench 评测")), /* @__PURE__ */ __h("nav", { className: "pbe-rail__nav", "aria-label": "模块" }, nav.map((item) => /* @__PURE__ */ __h(
    "button",
    {
      key: item.key,
      type: "button",
      className: "pbe-nav-item",
      "aria-current": surface === item.key ? "page" : void 0,
      onClick: () => {
        setView(item.key);
        backToList();
      }
    },
    item.glyph,
    /* @__PURE__ */ __h("span", null, item.label),
    item.count ? /* @__PURE__ */ __h("span", { className: "pbe-nav-item__count" }, item.count) : null
  ))), /* @__PURE__ */ __h(Tooltip, { title: "点一下重新探测服务" }, /* @__PURE__ */ __h(
    "button",
    {
      type: "button",
      className: "pbe-rail__foot",
      onClick: () => {
        setView("settings");
        backToList();
      }
    },
    /* @__PURE__ */ __h("div", { style: { display: "flex", alignItems: "center", gap: "var(--spacer-6)" } }, /* @__PURE__ */ __h(
      StatusPill,
      {
        tone: jobsError ? "err" : config?.has_token ? "ok" : "warn",
        label: jobsError ? "服务不可用" : config?.has_token ? "已连接" : "未配置 token"
      }
    ), jobsLoading ? /* @__PURE__ */ __h(Reload, { style: { fontSize: 12, color: "var(--text-tertiary)" } }) : null),
    /* @__PURE__ */ __h("div", { className: "pbe-cell-sub", style: { marginTop: "var(--spacer-4)" } }, config?.base_url || "还没有填写地址")
  ))), /* @__PURE__ */ __h("main", { className: "pbe-main" }, bootError ? /* @__PURE__ */ __h(
    Alert,
    {
      type: "warning",
      showIcon: true,
      closable: true,
      message: "读不到连接配置",
      description: bootError,
      style: { marginBottom: "var(--spacer-16)" }
    }
  ) : null, jobsError ? /* @__PURE__ */ __h(
    Alert,
    {
      type: "error",
      showIcon: true,
      closable: true,
      message: jobsError.code,
      description: /* @__PURE__ */ __h(__Fragment, null, jobsError.message, /* @__PURE__ */ __h("br", null), "去看「配置」里的服务地址与 token；也可以点左边连接卡重新探测。"),
      style: { marginBottom: "var(--spacer-16)" }
    }
  ) : null, jobId ? /* @__PURE__ */ __h(ReportModule, { jobId, onBack: backToList }) : datasetId && taskId ? /* @__PURE__ */ __h(
    DatasetTaskModule,
    {
      datasetId,
      taskId,
      onBack: backToDataset
    }
  ) : datasetId ? /* @__PURE__ */ __h(
    DatasetDetailModule,
    {
      datasetId,
      onBack: backToDatasets,
      onOpenTask: openDatasetTask
    }
  ) : view === "jobs" ? /* @__PURE__ */ __h(
    JobsModule,
    {
      jobs,
      loading: jobsLoading,
      subject: config?.subject ?? "",
      onOpen: openReport,
      onRefresh: () => void refreshJobs(),
      onNew: () => setNewOpen(true)
    }
  ) : view === "datasets" ? /* @__PURE__ */ __h(DatasetsModule, { subject: config?.subject ?? "", onOpen: openDataset }) : /* @__PURE__ */ __h(
    SettingsModule,
    {
      config,
      format,
      onSaved: (next) => {
        setConfig(next);
        void refreshJobs();
      },
      onFormat: (value) => {
        setFormat(value);
        store(FORMAT_KEY, value);
      }
    }
  ))), /* @__PURE__ */ __h(
    NewJobModal,
    {
      open: newOpen,
      onClose: () => setNewOpen(false),
      onIdentity: (subject) => setConfig((prev) => prev ? { ...prev, subject } : prev),
      onSubmitted: (job) => {
        setNewOpen(false);
        void refreshJobs();
        openReport(job.job_id);
      }
    }
  )));
}

// src/index.tsx
var STYLE_ID = "pawbench-eval-styles";
function injectStyles() {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = [colors_and_type_default, components_default, styles_default].join("\n");
  document.head.appendChild(style);
}
function main() {
  const sdk = window.QwenPaw;
  if (!sdk?.host || typeof sdk.registerRoutes !== "function") {
    console.error("[pawbench-eval] window.QwenPaw host SDK is not ready");
    return;
  }
  host();
  injectStyles();
  sdk.registerRoutes("pawbench-eval", [
    {
      path: "/apps/pawbench-eval",
      component: Shell,
      label: "PawBench 评测",
      icon: "🧪",
      priority: 60
    }
  ]);
}
main();
