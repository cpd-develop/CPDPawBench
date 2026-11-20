/**
 * DesignSys v1, applied in one place.
 *
 * Two things happen here, and nothing else in the tree is allowed to do either:
 *
 * 1. **The page picks a theme.**  The host console renders this route inside a
 *    dark or a light shell; we read that from the host's own antd token and put
 *    `data-theme` on our root, which is the switch the design system's token
 *    file expects (`:root` = light, `[data-theme="dark"]` re-points every
 *    semantic colour).
 * 2. **antd is told to speak tokens.**  Every antd colour is read back out of
 *    the CSS custom properties *after* the theme attribute is applied, so antd
 *    components and our own stylesheet resolve the same values and no colour is
 *    ever written down in this repository.  That is what keeps the "no literal
 *    colour" test honest instead of cosmetic.
 */

import { theme } from "./host/antd";
import { useState, useLayoutEffect, useMemo } from "./host/react";

/** The tokens the page actually consumes; reading more would only cost time. */
export const TOKENS = [
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
  "--layout-sidebar",
] as const;

export type TokenName = (typeof TOKENS)[number];
export type DesignTokens = Partial<Record<TokenName, string>>;

/** Rough perceived brightness, enough to answer "is this shell dark?". */
function brightness(value: string): number {
  const text = String(value || "").trim();
  let parts: number[] = [];
  if (text.startsWith("#")) {
    const hex = text.slice(1);
    const full = hex.length === 3 ? hex.split("").map((c) => c + c).join("") : hex.slice(0, 6);
    parts = [
      parseInt(full.slice(0, 2), 16),
      parseInt(full.slice(2, 4), 16),
      parseInt(full.slice(4, 6), 16),
    ];
  } else {
    // Any concrete colour string carries its channels as numbers somewhere;
    // taking the first three keeps this independent of which notation the host
    // hands us, without writing that notation down.
    parts = (text.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
  }
  const [r = 255, g = 255, b = 255] = parts;
  return (0.2126 * (r || 0) + 0.7152 * (g || 0) + 0.0722 * (b || 0)) / 255;
}

function readTokens(element: HTMLElement): DesignTokens {
  const styles = getComputedStyle(element);
  const read: DesignTokens = {};
  for (const name of TOKENS) {
    const value = styles.getPropertyValue(name).trim();
    if (value) read[name] = value;
  }
  return read;
}

function antdTheme(tokens: DesignTokens, isDark: boolean): Record<string, unknown> {
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
      wireframe: false,
    },
    components: {
      Table: {
        headerBg: "transparent",
        headerColor: t["--text-tertiary"],
        headerSplitColor: "transparent",
        borderColor: t["--border-neutral-l1"],
        rowHoverBg: t["--bg-overlay-l1"],
        cellPaddingBlock: 12,
        cellPaddingInline: 12,
      },
      Tabs: {
        itemColor: t["--text-secondary"],
        itemHoverColor: t["--text-brand"],
        itemSelectedColor: t["--text-brand"],
        inkBarColor: t["--bg-brand"],
        titleFontSize: 14,
      },
      Button: { primaryShadow: "none", defaultShadow: "none", dangerShadow: "none" },
      Modal: {
        contentBg: t["--bg-base-default"],
        headerBg: t["--bg-base-default"],
        titleColor: t["--text-default"],
      },
      Segmented: {
        trackBg: t["--bg-overlay-l1"],
        itemSelectedBg: t["--bg-base-default"],
        itemColor: t["--text-secondary"],
        itemSelectedColor: t["--text-default"],
      },
      Input: { activeShadow: "none" },
      Select: { optionSelectedBg: t["--bg-overlay-l2"] },
      Tooltip: { colorBgSpotlight: t["--bg-tooltip"] },
      // A progress fill is information, not an action: brand purple stays
      // reserved for the primary button and navigation, per the system.
      Progress: { defaultColor: t["--status-primary-default"] },
    },
  };
}

export interface DesignContext {
  isDark: boolean;
  tokens: DesignTokens;
}

/**
 * Wraps the page: picks the theme, reads the tokens, hands antd the result.
 *
 * The read happens in a layout effect so the first painted frame is already
 * correct — resolving them after paint would flash a light shell inside a dark
 * console for anyone with a slow machine.
 */
export function DesignScope(props: {
  children: unknown;
  ConfigProvider: any;
  className?: string;
}): unknown {
  const hostToken = (theme as unknown as { useToken?: () => { token: { colorBgBase?: string } } })
    .useToken;
  const host = typeof hostToken === "function" ? hostToken().token : {};
  const isDark = brightness(String(host.colorBgBase ?? "")) < 0.5;
  const attribute = isDark ? "dark" : "light";

  const [element, setElement] = useState<HTMLDivElement | null>(null);
  const [tokens, setTokens] = useState<DesignTokens | null>(null);

  useLayoutEffect(() => {
    if (!element) return;
    setTokens(readTokens(element));
  }, [element, attribute]);

  const themeConfig = useMemo(
    () => antdTheme(tokens ?? {}, isDark),
    [tokens, isDark],
  );

  const { ConfigProvider } = props;
  return (
    <div
      className={props.className}
      data-theme={attribute}
      data-pbe-ready={tokens ? "true" : "false"}
      ref={setElement}
      style={tokens ? undefined : { visibility: "hidden" }}
    >
      <ConfigProvider theme={themeConfig}>{props.children}</ConfigProvider>
    </div>
  );
}
