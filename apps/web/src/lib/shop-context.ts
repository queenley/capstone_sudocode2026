// What the shopper is looking at, and whether the chat is open: shared between
// pages (a product page sets the product) and the chat widget (which sends it
// with each message as `selected_sku`, and opens on "Hỏi tư vấn").
import { useSyncExternalStore } from "react";

type State = { sku: string; productName: string; chatOpen: boolean; draft: string };

let state: State = { sku: "", productName: "", chatOpen: false, draft: "" };
const listeners = new Set<() => void>();
let chatTrigger: HTMLElement | null = null;

function set(patch: Partial<State>) {
  state = { ...state, ...patch };
  listeners.forEach((listener) => listener());
}

export const shopContext = {
  viewing(sku: string, productName: string) {
    set({ sku, productName });
  },
  leave() {
    set({ sku: "", productName: "" });
  },
  openChat(draft = "") {
    if (!state.chatOpen) chatTrigger = document.activeElement as HTMLElement | null;
    set({ chatOpen: true, draft });
  },
  closeChat() {
    const trigger = chatTrigger;
    chatTrigger = null;
    set({ chatOpen: false });
    requestAnimationFrame(() => { if (trigger?.isConnected) trigger.focus(); });
  },
  takeDraft(): string {
    const draft = state.draft;
    if (draft) state = { ...state, draft: "" };
    return draft;
  },
};

export function useShopContext(): State {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => state,
    () => state,
  );
}
