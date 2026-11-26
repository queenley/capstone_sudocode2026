// The developer console's live feed (GET /api/developer/live/stream, server-sent events): read with fetch so the
// staff token goes in the Authorization header (EventSource cannot set one). The server ends each stream after
// about 100 s; this reconnects from the last turn it saw, waiting longer after each failure.

export type LiveTool = { name: string | null; ok: boolean; error: string | null; blocked_by: string | null; args: string[] };
export type LiveTurn = {
  id: number;
  call_id: number;
  turn_id: string;
  at: string | null;
  channel: string | null;
  mode: string | null;
  lane: string | null;
  route_reason: string | null;
  tier: string | null;
  model: string | null;
  ttft_ms: number | null;
  total_ms: number | null;
  stages: Record<string, number>;
  warmup: boolean;
  model_calls: number;
  tokens: { input: number | null; output: number | null; cached: number | null };
  cost_usd: number | null;
  by_agent: Record<string, { calls: number; input: number; output: number; cached: number; cost_usd: number }>;
  tools: LiveTool[];
  guard: { passed: boolean; reasons: string[] };
  regenerations: number;
  fallback: boolean;
  error: string | null;
  handoff: boolean;
  langfuse_url: string | null;
};
export type LiveSummary = {
  minutes: number;
  turns: number;
  ttft_p50_ms: number | null;
  ttft_p95_ms: number | null;
  total_p95_ms: number | null;
  tokens_input: number;
  tokens_output: number;
  tokens_per_turn: number | null;
  cost_usd: number | null;
  tool_calls: number;
  tool_failures: number;
  guard_blocks: number;
  errors: number;
  fallbacks: number;
  handoffs: number;
  by_tool: Record<string, { calls: number; failed: number }>;
  by_model: Record<string, number>;
  langfuse: boolean;
  spend_today_usd: number | null;
  load: { turns: number; calls: number; pods: number; shared: boolean };
};

/** Split an SSE body into its events; returns the events and what is left of an unfinished one. */
export function parseEvents(buffer: string): { events: { event: string; data: string }[]; rest: string } {
  const events: { event: string; data: string }[] = [];
  const blocks = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = blocks.pop() ?? "";
  for (const block of blocks) {
    let event = "message";
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue; // a heartbeat comment
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
    }
    if (data.length) events.push({ event, data: data.join("\n") });
  }
  return { events, rest };
}

/** Follow new turns until *signal* aborts. *onTurn* hears each one; *onState* whether the feed is connected. */
export async function followTurns(
  token: string,
  after: number | null,
  onTurn: (turn: LiveTurn) => void,
  onState: (state: "connected" | "reconnecting" | "error", detail?: string) => void,
  signal: AbortSignal,
): Promise<void> {
  let last = after;
  let wait = 1000;
  while (!signal.aborted) {
    try {
      const response = await fetch(`/backend/api/developer/live/stream${last != null ? `?after=${last}` : ""}`, {
        headers: { Authorization: "Bearer " + token, Accept: "text/event-stream" },
        cache: "no-store",
        signal,
      });
      if (response.status === 401 || response.status === 403) {
        onState("error", "Token không có quyền developer hoặc admin.");
        return;
      }
      if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
      onState("connected");
      wait = 1000;
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parsed = parseEvents(buffer);
        buffer = parsed.rest;
        for (const item of parsed.events) {
          const data = JSON.parse(item.data);
          if (item.event === "turn") {
            last = data.id;
            onTurn(data as LiveTurn);
          } else if (item.event === "hello" || item.event === "bye") {
            last = data.after ?? last;
          }
        }
      }
    } catch (error) {
      if (signal.aborted) return;
      onState("reconnecting", error instanceof Error ? error.message : undefined);
      await new Promise((done) => setTimeout(done, wait));
      wait = Math.min(wait * 2, 10_000);
      continue;
    }
    // The server closed the stream on time: reconnect at once from the last id.
  }
}
