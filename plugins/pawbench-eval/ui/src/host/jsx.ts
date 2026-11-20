/**
 * The JSX factory, injected into every file that contains JSX (see build.mjs).
 *
 * It is a two-line module on purpose: JSX must compile to the host's own
 * `createElement`, because the host's React is the one whose hooks and context
 * the surrounding console is already running on.  A bundled second copy would
 * produce elements this tree can render but whose hooks belong to a different
 * dispatcher.
 */

const React = window.QwenPaw?.host?.React;

export const __h = (React as { createElement: (...args: unknown[]) => unknown }).createElement;

export const __Fragment = (React as { Fragment: unknown }).Fragment;
