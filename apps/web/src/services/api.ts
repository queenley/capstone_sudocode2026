export async function api<T = unknown>(
  path: string,
  token = "",
  body?: unknown,
  method?: string,
): Promise<T> {
  const response = await fetch("/backend" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: "Bearer " + token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  // A proxy or a crashed service answers with a text page ("Internal Server Error"), not JSON.
  const raw = await response.text();
  let result: { detail?: unknown } & Record<string, unknown>;
  try {
    result = raw ? JSON.parse(raw) : {};
  } catch {
    throw new Error(
      response.ok
        ? "Máy chủ trả về dữ liệu không đọc được. Vui lòng thử lại."
        : `Máy chủ đang gặp sự cố (${response.status}). Vui lòng thử lại sau ít phút.`,
    );
  }
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : Array.isArray(result.detail) && typeof result.detail[0]?.msg === "string"
          ? result.detail[0].msg
          : JSON.stringify(result.detail || result),
    );
  return result as T;
}

/** Source catalog shape from evaluation/data-generation/data/catalog/products.json. */
export type CatalogProductVariant = {
  variant_sku: string;
  size: string | number;
  color: string;
  price_delta_vnd: number;
  stock: number;
};

export type CatalogSourceProduct = {
  sku: string;
  name: string;
  category: string;
  brand: string;
  list_price_vnd: number;
  attributes: Record<string, unknown>;
  stock: number;
  variants: CatalogProductVariant[];
};

/** Product model used by the create-data pipeline and its source JSON. */
export type Product = CatalogSourceProduct;

export type ProductCatalog = {
  reference_date: string;
  currency: string;
  products: CatalogSourceProduct[];
};

/** Admin write contract for the current Commerce API, not the source JSON. */
export type CreateCatalogSkuInput = {
  name: string;
  brand: string;
  category: string;
  description?: string;
  sku_code: string;
  variant?: Record<string, string>;
  list_price: string;
  sale_price: string;
  stock: number;
};

/** Flattened Commerce API wire item, retained for the current HTTP backend. */
/** Who made a product photo and under which licence (CC BY asks for this next to the picture). */
export type ImageCredit = {
  title: string;
  author: string;
  author_url: string;
  license: string;
  license_url: string;
  source_url: string;
  provider: string;
};
export type CommerceCatalogItem = {
  id: string;
  name: string;
  brand: string;
  category: string;
  description: string | null;
  /** A photo on this site ("/products/<ref>.jpg"), or null: the category's drawing is shown. */
  image_url?: string | null;
  image_credit?: ImageCredit | null;
  sku_code: string;
  variant: Record<string, unknown>;
  list_price: string;
  sale_price: string;
  currency: string;
  available: number;
};
export type Session = { conversation_id: string; conversation_token: string };
export type ChatMessage = { speaker: string; text: string };
export type TurnResult = {
  reply: string;
  route: string;
  confidence: number;
  trace_id: string;
  products: CommerceCatalogItem[];
  stages?: string[];
  stage_timings_ms?: Record<string, number>;
  tool_calls?: string[];
  signals?: Record<string, unknown>;
  /** True when a person has the conversation: the assistant did not answer. */
  waiting?: boolean;
  replayed?: boolean;
};

/** One call in the agent's console (`/api/agent/calls`). */
export type AgentCall = {
  id: number;
  conversation_id: string | null;
  phone_last4: string | null;
  channel: string;
  channel_ref: string | null;
  tier: "VERIFIED" | "PROBABLE" | "AMBIGUOUS" | "UNKNOWN";
  lane: string;
  route_reason: string | null;
  mode: "speak" | "copilot";
  customer_id: string | null;
  customer_label: string | null;
  brief: { id: string; text: string; sensitive?: boolean }[];
  brief_object: {
    is_returning?: boolean;
    must_not_ask?: string[];
    suggested_opening?: string;
    latency_ms?: number;
  } | null;
  warnings: string[];
  business_day: string | null;
  started_at: string;
  ended_at: string | null;
  turn_count: number;
  handoff_status: "pending" | "accepted" | null;
  handoff_reason: string | null;
  handoff_brief: Record<string, unknown> | null;
  accepted_by: string | null;
  suggestion: { text: string; used_lines?: string[]; warnings?: string[] } | null;
  memory_status: string | null;
  after_call: Record<string, unknown> | null;
};

export type AgentTurn = {
  id: number;
  turn_id: string;
  speaker: "customer" | "agent" | "human_agent" | "system";
  content: string;
  meta: Record<string, unknown>;
  created_at: string;
};

export type AgentCallDetail = AgentCall & { held_by_you: boolean; turns: AgentTurn[] };

/** A cart line sent with a chat message: the cart lives in this browser, so the assistant
 *  only knows it from here. `name` is the product as the shop shows it. */
export type ChatCartLine = { sku: string; qty: number; name?: string };

export async function streamTurn(
  session: Session,
  message: string,
  selectedSku: string,
  onText: (text: string) => void,
  cartLines: ChatCartLine[] | null = null,
): Promise<TurnResult> {
  const response = await fetch(
    `/backend/api/conversations/${session.conversation_id}/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + session.conversation_token,
      },
      body: JSON.stringify({ message, selected_sku: selectedSku || null, cart: cartLines }),
    },
  );
  if (!response.ok || !response.body)
    throw new Error("Chat request failed. Please refresh and retry.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    text = "",
    result: TurnResult | undefined;
  while (true) {
    const chunk = await reader.read();
    buffer += decoder.decode(chunk.value || new Uint8Array(), {
      stream: !chunk.done,
    });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) >= 0) {
      const event = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const name = event
        .split("\n")
        .find((line) => line.startsWith("event:"))
        ?.slice(6)
        .trim();
      const data = event
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (!data) continue;
      const payload = JSON.parse(data);
      if (name === "delta") {
        text += payload.text;
        onText(text);
      }
      if (name === "done") result = payload;
      if (name === "error")
        throw new Error(
          typeof payload.message === "string"
            ? payload.message
            : JSON.stringify(payload.message),
        );
    }
    if (chunk.done) break;
  }
  if (!result)
    throw new Error(
      "The response was interrupted. Refresh the conversation before retrying.",
    );
  return result;
}
