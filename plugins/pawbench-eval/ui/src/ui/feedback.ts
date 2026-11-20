/**
 * Toasts, via the host's antd `App` when it is there.
 *
 * The static `message` export renders into a container with no provider around
 * it, so it carries the default light theme — a white toast over a dark page.
 * `App.useApp()` keeps the toast inside our ConfigProvider and therefore inside
 * the token set.  The static export stays as a fallback for a host build whose
 * antd predates `App`.
 */

import { App, message as staticMessage, Modal } from "../host/antd";

const app = App as unknown as { useApp?: () => { message: unknown; modal: unknown } };

export interface Feedback {
  message: { success: (text: string) => void; info: (text: string) => void; error: (text: string) => void };
  modal: any;
}

export function useFeedback(): Feedback {
  const context = typeof app?.useApp === "function" ? app.useApp() : null;
  return {
    message: (context?.message as Feedback["message"]) ?? (staticMessage as Feedback["message"]),
    modal: context?.modal ?? Modal,
  };
}
