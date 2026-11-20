/**
 * The host's React hooks, renamed to what this code actually uses.
 *
 * Not `import { useState } from "react"`: there is no bundled React (the host
 * owns it) and a Blob-loaded module cannot resolve a bare specifier.  Naming
 * them here keeps the call sites looking like ordinary React.
 */

const React = window.QwenPaw?.host?.React as Record<string, any>;

export const useState = React.useState as <T>(
  initial: T | (() => T),
) => [T, (next: T | ((prev: T) => T)) => void];

export const useEffect = React.useEffect as (effect: () => void | (() => void), deps?: unknown[]) => void;

export const useLayoutEffect = React.useLayoutEffect as (
  effect: () => void | (() => void),
  deps?: unknown[],
) => void;

export const useMemo = React.useMemo as <T>(factory: () => T, deps: unknown[]) => T;

export const useCallback = React.useCallback as <T extends (...args: any[]) => any>(
  fn: T,
  deps: unknown[],
) => T;

export const useRef = React.useRef as <T>(initial: T) => { current: T };
