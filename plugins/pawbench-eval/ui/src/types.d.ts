/**
 * The host SDK is untyped JavaScript, and this package ships no `@types/react`:
 * React, antd and the icons are whatever the loaded QwenPaw build exposes.  A
 * local JSX namespace is therefore the honest description of the situation --
 * elements are `any`, and everything that can be typed (our own components,
 * the API payloads) is typed in its own module.
 *
 * `__h` / `__Fragment` are not imported anywhere: `build.mjs` injects this pair
 * into every file that contains JSX, which is what lets the bundle stay free of
 * bare module specifiers.
 */

declare const __h: (type: unknown, props?: unknown, ...children: unknown[]) => unknown;
declare const __Fragment: unknown;

declare namespace JSX {
  type Element = unknown;

  interface IntrinsicElements {
    [element: string]: unknown;
  }

  interface ElementChildrenAttribute {
    children: unknown;
  }

  /** `key` is React's, not a component's, and belongs on every element. */
  interface IntrinsicAttributes {
    key?: string | number;
  }
}

/** CSS arrives as text (see build.mjs): the loader hands back the file's source. */
declare module "*.css" {
  const content: string;
  export default content;
}

interface Window {
  QwenPaw?: {
    host: {
      React: Record<string, unknown>;
      antd: Record<string, unknown>;
      antdIcons?: Record<string, unknown>;
      getApiUrl: (path: string) => string;
      getApiToken?: () => string;
    };
    registerRoutes?: (
      pluginId: string,
      routes: {
        path: string;
        component: unknown;
        label?: string;
        icon?: string;
        priority?: number;
      }[],
    ) => void;
  };
}
