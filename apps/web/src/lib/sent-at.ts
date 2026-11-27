// Testing aid: the moment a chat message or a call says it was sent.
//
// The agent reads stock, promotions and working hours on its own clock
// (by default 10:00 on 15/10/2026, the organisers' day). A tester picks
// another moment in the chat window to see the agent on that day and hour;
// it goes with each message as `sent_at` and with a call's first frame.
// Empty means the shop's clock. The backend ignores it in production unless
// CLIENT_CLOCK=1 (apps/ai-agent-service runtime/options.py).

import { useSyncExternalStore } from "react";

const KEY = "quivo.sent_at";
const listeners = new Set<() => void>();

/** `YYYY-MM-DDTHH:MM` in Vietnam time, or "" for the shop's clock. */
export function getSentAt(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}

export function setSentAt(value: string) {
  try {
    if (value) window.localStorage.setItem(KEY, value);
    else window.localStorage.removeItem(KEY);
  } catch {
    // Private mode: the choice lasts only until the page reloads.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useSentAt(): [string, (value: string) => void] {
  const value = useSyncExternalStore(subscribe, getSentAt, () => "");
  return [value, setSentAt];
}
