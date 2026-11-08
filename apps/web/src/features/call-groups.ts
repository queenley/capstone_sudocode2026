// The queue shows one row per customer, not per session: a customer who wrote
// on the web, then on Zalo, then called the hotline is one person to the team.
// Sessions join only on the CRM customer the agent identified (`customer_id`);
// a session with no known customer stays a row of its own, since a shared
// number or a guest is nobody we may join.
import { AgentCall } from "@/services/api";

export type CallGroup = {
  key: string;
  /** Newest first. */
  calls: AgentCall[];
  /** The session the row opens: one waiting for staff, else one still open, else the newest. */
  lead: AgentCall;
  waiting: boolean;
  live: boolean;
};

const pending = (c: AgentCall) => c.handoff_status === "pending" && !c.ended_at;

export function groupCalls(calls: AgentCall[]): CallGroup[] {
  const byKey = new Map<string, AgentCall[]>();
  for (const c of calls) {
    const key = c.customer_id ? `customer:${c.customer_id}` : `call:${c.id}`;
    const list = byKey.get(key);
    if (list) list.push(c);
    else byKey.set(key, [c]);
  }
  const groups = [...byKey].map(([key, list]) => {
    const sorted = [...list].sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
    return {
      key,
      calls: sorted,
      lead: sorted.find(pending) || sorted.find((c) => !c.ended_at) || sorted[0],
      waiting: sorted.some(pending),
      live: sorted.some((c) => !c.ended_at),
    };
  });
  // Who waits for a person first, then who is still talking, then the most recent.
  return groups.sort(
    (a, b) =>
      Number(b.waiting) - Number(a.waiting) ||
      Number(b.live) - Number(a.live) ||
      Date.parse(b.calls[0].started_at) - Date.parse(a.calls[0].started_at),
  );
}

export function groupOf(groups: CallGroup[], callId: number | null): CallGroup | undefined {
  return callId == null ? undefined : groups.find((g) => g.calls.some((c) => c.id === callId));
}
