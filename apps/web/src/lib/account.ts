// The shopper's account (Identity `/api/customer/*`): register with a one-time code,
// log in with phone and password, the profile, and logging out.
//
// Logging in stores the same customer token the phone check already used
// (lib/session.ts), so the order pages, checkout and the chat all know the
// shopper. On login the chat starts a new conversation (linked to the account,
// so the assistant can read the account's cart and orders) and the browser's
// cart is merged into the account's (lib/cart.ts); on logout both are let go.
import { useSyncExternalStore } from "react";
import { api } from "@/services/api";
import { cart } from "@/lib/cart";
import { customerToken, forgetConversation, setCustomerToken } from "@/lib/session";

export type Account = {
  customer_id: string;
  full_name: string | null;
  phone: string | null;
  email: string | null;
  /** False for a shopper who only verified a phone in the chat or at checkout (no password yet). */
  registered: boolean;
  registered_at: string | null;
};

export type CodeSent = { challenge_id: string; delivery: string; development_code?: string };
type Session = { customer_token: string; account: Account };

type State = { status: "unknown" | "guest" | "signed-in"; account: Account | null };

let state: State = { status: "unknown", account: null };
const listeners = new Set<() => void>();
let loading: Promise<void> | null = null;

function set(next: State) {
  state = next;
  listeners.forEach((listener) => listener());
}

async function begin(session: Session) {
  setCustomerToken(session.customer_token);
  forgetConversation();
  set({ status: "signed-in", account: session.account });
  await cart.attach(session.customer_token);
}

export const account = {
  /** Who is signed in, from the saved token; once per page load unless forced. */
  load(force = false): Promise<void> {
    if (loading && !force) return loading;
    const token = customerToken();
    if (!token) {
      set({ status: "guest", account: null });
      return (loading = Promise.resolve());
    }
    loading = api<Account>("/api/customer/me", token)
      .then(async (me) => {
        if (customerToken() !== token) return;
        set({ status: "signed-in", account: me });
        await cart.attach(token);
      })
      .catch((error) => {
        if (customerToken() !== token || ![401, 403].includes(error?.status)) return;
        // Expired or revoked: the shopper is a guest again.
        setCustomerToken(null);
        forgetConversation();
        cart.detach();
        set({ status: "guest", account: null });
      });
    return loading;
  },
  async login(phone: string, password: string) {
    await begin(await api<Session>("/api/customer/login", "", { phone, password }));
  },
  registerStart(input: { full_name: string; phone: string; password: string; email?: string }) {
    return api<CodeSent>("/api/customer/register/start", "", input);
  },
  async registerVerify(challengeId: string, code: string) {
    await begin(await api<Session>("/api/customer/register/verify", "", { challenge_id: challengeId, code }));
  },
  resetStart(phone: string) {
    return api<CodeSent>("/api/customer/password/reset/start", "", { phone });
  },
  async resetVerify(challengeId: string, code: string, password: string) {
    await begin(await api<Session>("/api/customer/password/reset/verify", "", { challenge_id: challengeId, code, password }));
  },
  async update(changes: { full_name?: string; email?: string }) {
    const me = await api<Account>("/api/customer/me", customerToken(), changes, "PATCH");
    set({ status: "signed-in", account: me });
    return me;
  },
  changePassword(current: string, next: string) {
    return api("/api/customer/password", customerToken(), { current_password: current, new_password: next });
  },
  async logout() {
    const token = customerToken();
    setCustomerToken(null);
    forgetConversation();
    cart.detach();
    set({ status: "guest", account: null });
    if (token) await api("/api/customer/logout", token, {}).catch(() => undefined);
  },
  /** After the phone check at checkout or on the order page: the token is new, read who it is.
   *  The conversation stays: the code was checked on it, so it already belongs to this customer. */
  verified() {
    return account.load(true);
  },
};

export function useAccount(): State {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      if (listeners.size === 1) window.addEventListener("storage", changedAccount);
      if (state.status === "unknown") account.load();
      return () => {
        listeners.delete(listener);
        if (!listeners.size) window.removeEventListener("storage", changedAccount);
      };
    },
    () => state,
    () => state,
  );
}

function changedAccount(event: StorageEvent) {
  if (event.key !== "customer-token" && event.key !== null) return;
  forgetConversation();
  cart.detach();
  void account.load(true);
}

/** "Nguyễn Thị Oanh" -> "Oanh", as the header greets: Vietnamese names end with the given name. */
export function firstName(account: Account | null): string {
  const words = (account?.full_name || "").trim().split(/\s+/);
  return words[words.length - 1] || "bạn";
}
