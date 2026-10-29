// The shopper's conversation with the shop (Sales `POST /api/conversations`)
// and their verified-customer token (Identity OTP), shared by the chat widget,
// the voice call and checkout.
//
// - The conversation lives in sessionStorage ("conversation"), as before: a new
//   tab starts a new conversation.
// - The customer token lives in localStorage ("customer-token"): a verified
//   shopper stays recognised on this device until they delete their data.
import { api, Session } from "@/services/api";

export type ShopSession = Session & { customer_id?: string | null };

const CONVERSATION = "conversation";
const CUSTOMER = "customer-token";
const OWNER = "conversation-customer";
let opening: Promise<ShopSession> | null = null;

export function customerToken(): string {
  try {
    return localStorage.getItem(CUSTOMER) || "";
  } catch {
    return "";
  }
}

export function setCustomerToken(token: string | null) {
  try {
    if (token) localStorage.setItem(CUSTOMER, token);
    else localStorage.removeItem(CUSTOMER);
  } catch {
    /* ignore */
  }
}

/** Drop this tab's conversation: the next message starts one as whoever is signed in now. */
export function forgetConversation() {
  opening = null;
  try {
    sessionStorage.removeItem(CONVERSATION);
    sessionStorage.removeItem(OWNER);
  } catch {
    /* ignore */
  }
  window.dispatchEvent(new Event("shop-conversation-reset"));
}

export function savedSession(): ShopSession | null {
  try {
    const saved = sessionStorage.getItem(CONVERSATION);
    const owner = sessionStorage.getItem(OWNER);
    if (owner !== null && owner !== customerToken()) return null;
    return saved ? (JSON.parse(saved) as ShopSession) : null;
  } catch {
    return null;
  }
}

export async function newSession(): Promise<ShopSession> {
  const token = customerToken();
  const session = await api<ShopSession>("/api/conversations", token, {});
  if (customerToken() !== token) throw new Error("Tài khoản đã thay đổi. Vui lòng mở lại cuộc trò chuyện.");
  try {
    sessionStorage.setItem(CONVERSATION, JSON.stringify(session));
    sessionStorage.setItem(OWNER, token);
  } catch {
    /* ignore */
  }
  return session;
}

export type ConversationState = {
  messages: { speaker: string; text: string }[];
  status: string;
  customer_id: string | null;
};

export function loadConversation(session: Session) {
  return api<ConversationState>(`/api/conversations/${session.conversation_id}`, session.conversation_token);
}

/** The saved conversation if it is still open, otherwise a new one. */
export function openSession(): Promise<ShopSession> {
  if (opening) return opening;
  const pending = resumeSession().finally(() => {
    if (opening === pending) opening = null;
  });
  opening = pending;
  return pending;
}

async function resumeSession(): Promise<ShopSession> {
  const saved = savedSession();
  if (saved) {
    try {
      const state = await loadConversation(saved);
      if (state.status === "open" || state.status === "handed_off") return { ...saved, customer_id: state.customer_id };
    } catch {
      /* expired or deleted: start again */
    }
  }
  return newSession();
}
