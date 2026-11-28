import type { TurnStep } from "@/components/ui/StepTrail";
import { getSentAt } from "@/lib/sent-at";

/** GET /api/agent/welcome: authenticated agent memory, with no call/message side effect. */
export type ReturningCustomerWelcome = {
  returning: boolean;
  name: string | null;
  blocker: { text: string; valid_until: string } | null;
  expires_at: string;
};

export async function api<T = unknown>(
  path: string,
  token = "",
  body?: unknown,
  method?: string,
  options: { signal?: AbortSignal } = {},
): Promise<T> {
  const response = await fetch("/backend" + path, {
    method: method || (body === undefined ? "GET" : "POST"),
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(token ? { Authorization: "Bearer " + token } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
    signal: options.signal
      ? AbortSignal.any([options.signal, AbortSignal.timeout(30_000)])
      : AbortSignal.timeout(30_000),
  });
  // A proxy or a crashed service answers with a text page ("Internal Server Error"), not JSON.
  const raw = await response.text();
  let result: { detail?: unknown } & Record<string, unknown>;
  try {
    result = raw ? JSON.parse(raw) : {};
  } catch {
    throw Object.assign(
      new Error(
        response.ok
          ? "Máy chủ trả về dữ liệu không đọc được. Vui lòng thử lại."
          : `Máy chủ đang gặp sự cố (${response.status}). Vui lòng thử lại sau ít phút.`,
      ),
      { status: response.status },
    );
  }
  if (!response.ok)
    throw Object.assign(
      new Error(
        typeof result.detail === "string"
          ? result.detail
          : Array.isArray(result.detail) &&
              typeof result.detail[0]?.msg === "string"
            ? result.detail[0].msg
            : typeof (result.detail as { message?: unknown })?.message ===
                "string"
              ? String((result.detail as { message: string }).message)
              : "Yêu cầu chưa thực hiện được. Vui lòng thử lại.",
      ),
      { status: response.status, detail: result.detail },
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
/** A VietQR to pay one order by bank transfer, as the assistant's order_payment_qr or order_create made it. */
export type PaymentQr = {
  order_id: string | null;
  amount_vnd: number | null;
  transfer_note: string | null;
  bank_name: string | null;
  account_name: string | null;
  account_no: string | null;
  qr_url: string;
};
export type TurnResult = {
  reply: string;
  route: string;
  confidence: number;
  trace_id: string;
  products: CommerceCatalogItem[];
  /** The transfer QR this turn's tools made, shown under the reply (api/routes/conversations.py payment_qr_of). */
  payment_qr?: PaymentQr | null;
  /** Manufacturer pages a reviewer approved with the knowledge that answered this turn (docs/plan/002, section 12). */
  references?: { url: string; domain: string; title: string }[];
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
  /** Not identified in this session, but the number given is this CRM customer's alone: grouped with them. */
  number_customer_id?: string | null;
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
  /** When the handoff was asked for; absent on older rows. */
  handoff_requested_at?: string | null;
  accepted_by: string | null;
  suggestion: {
    text: string;
    used_lines?: string[];
    warnings?: string[];
  } | null;
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

export type AgentCallDetail = AgentCall & {
  held_by_you: boolean;
  /** The tool steps of the turn the assistant is taking now (runtime/steps.py); empty between turns. */
  live_steps?: TurnStep[];
  turns: AgentTurn[];
};

/** A cart line sent with a chat message: the cart lives in this browser, so the assistant
 *  only knows it from here. `name` is the product as the shop shows it. */
export type ChatCartLine = { sku: string; qty: number; name?: string };

/** One voice message as text (POST /api/conversations/{id}/voice-message): 16-bit mono PCM at 16 kHz in, the words
 *  the recogniser heard out. Only transcribes: the chat sends the customer's voice messages as one turn. */
export async function transcribeVoice(
  session: Session,
  pcm: Int16Array,
  signal?: AbortSignal,
): Promise<{ text: string; seconds: number }> {
  const response = await fetch(`/backend/api/conversations/${session.conversation_id}/voice-message`, {
    method: "POST",
    headers: {
      "Content-Type": "application/octet-stream",
      Authorization: "Bearer " + session.conversation_token,
    },
    body: new Blob([pcm.slice().buffer], { type: "application/octet-stream" }),
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(60_000)]) : AbortSignal.timeout(60_000),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw Object.assign(new Error(typeof data.detail === "string" ? data.detail : "Không nhận dạng được tin nhắn thoại."), {
      status: response.status,
    });
  return data;
}

export async function streamTurn(
  session: Session,
  message: string,
  selectedSku: string,
  onText: (text: string) => void,
  cartLines: ChatCartLine[] | null = null,
  options: {
    signal?: AbortSignal;
    turnId?: string;
    /** Each tool step as it starts and ends (label only): components/ui/StepTrail.tsx. */
    onStep?: (step: TurnStep) => void;
  } = {},
): Promise<TurnResult> {
  const response = await fetch(
    `/backend/api/conversations/${session.conversation_id}/stream`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + session.conversation_token,
      },
      body: JSON.stringify({
        message,
        selected_sku: selectedSku || null,
        cart: cartLines,
        turn_id: options.turnId,
        sent_at: getSentAt() || null,
      }),
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(120_000)])
        : AbortSignal.timeout(120_000),
    },
  );
  if (!response.ok || !response.body)
    throw Object.assign(
      new Error("Không gửi được tin nhắn. Vui lòng tải lại cuộc trò chuyện."),
      { status: response.status },
    );
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "",
    text = "",
    result: TurnResult | undefined;
  try {
    while (true) {
      const chunk = await reader.read();
      buffer += decoder.decode(chunk.value || new Uint8Array(), {
        stream: !chunk.done,
      });
      let boundary;
      if (buffer.length > 2 * 1024 * 1024)
        throw new Error("Phản hồi vượt giới hạn cho phép.");
      let separator: RegExpExecArray | null;
      while ((separator = /\r?\n\r?\n/.exec(buffer))) {
        boundary = separator.index;
        const event = buffer.slice(0, boundary).replace(/\r\n/g, "\n");
        buffer = buffer.slice(boundary + separator[0].length);
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
        if (name === "step") options.onStep?.(payload as TurnStep);
        if (name === "done") {
          result = payload;
          break;
        }
        if (name === "error")
          throw new Error(
            typeof payload.message === "string"
              ? payload.message
              : JSON.stringify(payload.message),
          );
      }
      if (chunk.done || result) break;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  if (!result)
    throw new Error(
      "Phản hồi bị gián đoạn. Hãy tải lại lịch sử trước khi gửi tiếp.",
    );
  return result;
}
