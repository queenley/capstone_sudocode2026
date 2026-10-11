"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  api,
  streamTurn,
  CommerceCatalogItem,
  Session,
  ChatMessage,
} from "@/services/api";
import { VoiceCall } from "@/services/voice";
import VoiceCallPanel from "@/features/voice-call";

type Quote = CommerceCatalogItem & {
  total: string;
  discount: string;
  quantity: number;
  promotions: { description: string }[];
};
type ServiceHealth = {
  status: string;
  services: Record<string, string>;
};
const money = (value: string) =>
  new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(
    Number(value),
  );

export default function HomePage() {
  const [products, setProducts] = useState<CommerceCatalogItem[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [selected, setSelected] = useState("");
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("open");
  const [call, setCall] = useState<VoiceCall | null>(null);
  const [serviceHealth, setServiceHealth] = useState<ServiceHealth | null>(null);
  const [identityOpen, setIdentityOpen] = useState(false);
  const [phone, setPhone] = useState("");
  const [consent, setConsent] = useState(false);
  const [challenge, setChallenge] = useState<{
    challenge_id: string;
    development_code?: string;
  } | null>(null);
  const [code, setCode] = useState("");
  const [identified, setIdentified] = useState(false);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [address, setAddress] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [notice, setNotice] = useState("");
  const orderKey = useRef("");
  const bottom = useRef<HTMLDivElement>(null);

  async function start() {
    const customer = localStorage.getItem("customer-token") || "";
    const result = await api<Session & { customer_id: string | null }>(
      "/api/conversations",
      customer,
      {},
    );
    sessionStorage.setItem("conversation", JSON.stringify(result));
    setSession(result);
    setIdentified(!!result.customer_id);
    setMessages([]);
    setStatus("open");
  }
  async function load(s: Session) {
    const result = await api<{
      messages: ChatMessage[];
      status: string;
      customer_id: string | null;
    }>(`/api/conversations/${s.conversation_id}`, s.conversation_token);
    setMessages(result.messages);
    setStatus(result.status);
    setIdentified(!!result.customer_id);
  }
  async function action(task: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await task();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    api<CommerceCatalogItem[]>("/api/catalog")
      .then(setProducts)
      .catch((e) => setError(e.message));
    fetch("/backend/health/ready", { cache: "no-store" })
      .then(async (response) => {
        const snapshot = (await response.json()) as ServiceHealth;
        setServiceHealth(snapshot);
      })
      .catch(() => setServiceHealth({ status: "unavailable", services: {} }));
    const saved = sessionStorage.getItem("conversation");
    if (saved) {
      try {
        const s = JSON.parse(saved);
        setSession(s);
        load(s).catch((e) => setError(e.message));
      } catch {
        sessionStorage.removeItem("conversation");
      }
    }
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);
  useEffect(() => {
    if (!session || status !== "handed_off") return;
    const interval = setInterval(
      () => load(session).catch((e) => setError(e.message)),
      3000,
    );
    return () => clearInterval(interval);
  }, [session, status]);

  async function send() {
    if (!text.trim()) return;
    const content = text;
    setText("");
    await action(async () => {
      let s = session;
      if (!s) {
        const result = await api<Session>(
          "/api/conversations",
          localStorage.getItem("customer-token") || "",
          {},
        );
        s = result;
        setSession(result);
        sessionStorage.setItem("conversation", JSON.stringify(result));
      }
      if (status === "handed_off") {
        // Through the agent route: it records the words and, when the
        // assistant handed over, drafts a suggestion for the consultant.
        setMessages((old) => [...old, { speaker: "customer", text: content }]);
        await streamTurn(s, content, selected, () => {});
        await load(s);
        return;
      }
      setMessages((old) => [
        ...old,
        { speaker: "customer", text: content },
        { speaker: "assistant", text: "" },
      ]);
      await streamTurn(s, content, selected, (reply) =>
        setMessages((old) => [
          ...old.slice(0, -1),
          { speaker: "assistant", text: reply },
        ]),
      );
      await load(s);
    });
  }

  return (
    <main className="shell">
      <header className="topbar">
        <Link href="/" className="logo">
          <span className="logo-mark">t</span> tiếp
          <span className="logo-light">nối</span>
        </Link>
        <nav>
          <Link href="/agent">Agent workspace</Link>
          <Link href="/calls">Calls</Link>
          <Link href="/admin">Admin</Link>
          <Link href="/seller">Sales</Link>
          <Link href="/developer">Developer</Link>
        </nav>
        <span className="mode">
          {serviceHealth === null
            ? "Connecting…"
            : serviceHealth.services.ai_agent === "ready"
              ? "AI advisor online"
              : "AI advisor unavailable"}
        </span>
      </header>
      <section className="hero">
        <div>
          <p className="eyebrow">ONE CONVERSATION. EVERY VISIT.</p>
          <h1>
            Good advice remembers
            <br />
            where you left off.
          </h1>
          <p className="lede">
            Find your next device with an assistant that keeps the useful
            context.
            <br />
            Current prices. Real stock. A person when you need one.
          </p>
        </div>
        <div className="hero-note">
          <span className="spark">✦</span>
          <p>
            Your preferences travel
            <br />
            with you.
          </p>
          <small>Only with your consent.</small>
        </div>
      </section>
      <section className="service-status" aria-live="polite">
        <strong>Backend services</strong>
        <span
          className={
            "service-overall " +
            (serviceHealth?.status === "ready" ? "is-ready" : "is-degraded")
          }
        >
          {serviceHealth?.status === "ready"
            ? "All systems ready"
            : serviceHealth?.status === "degraded"
              ? "Some services need attention"
              : serviceHealth?.status === "unavailable"
                ? "Status unavailable"
                : "Checking services…"}
        </span>
        <div className="service-list">
          {Object.entries(serviceHealth?.services || {}).map(([name, status]) => (
            <span className="service-chip" key={name}>
              <i className={status === "ready" ? "health-dot" : "health-dot down"} />
              {name.replaceAll("_", " ")}
            </span>
          ))}
        </div>
      </section>
      {error && (
        <div className="alert" role="alert">
          {error}
          <button onClick={() => setError("")}>Dismiss</button>
        </div>
      )}
      {notice && (
        <div className="notice" role="status">
          {notice}
        </div>
      )}
      <div className="workgrid">
        <section className="catalog">
          <div className="section-heading">
            <div>
              <p className="eyebrow">THE COLLECTION</p>
              <h2>A few good options.</h2>
            </div>
            <span>{products.length} variants</span>
          </div>
          <form
            className="search"
            onSubmit={(e) => {
              e.preventDefault();
              action(async () =>
                setProducts(
                  await api<CommerceCatalogItem[]>(
                    "/api/catalog?q=" + encodeURIComponent(query),
                  ),
                ),
              );
            }}
          >
            <input
              aria-label="Search products"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search laptop, iPhone, ASUS…"
            />
            <button type="submit" disabled={busy}>
              Search
            </button>
          </form>
          <div className="productgrid">
            {products.map((p) => (
              <article
                className={
                  "product " + (selected === p.sku_code ? "selected" : "")
                }
                key={p.sku_code}
              >
                <div
                  className={
                    "device-art " +
                    (p.category.includes("laptop") ? "laptop" : "phone")
                  }
                  aria-hidden="true"
                >
                  <div className="device-screen">
                    <span>✦</span>
                  </div>
                  <div className="device-base" />
                </div>
                <div className="product-meta">
                  <span>{p.brand}</span>
                  <span className="stock">
                    {p.available > 0
                      ? `${p.available} available`
                      : "Out of stock"}
                  </span>
                </div>
                <h3>{p.name}</h3>
                <p className="variant">
                  {Object.values(p.variant).join(" · ")}
                  <br />
                  <small>{p.sku_code}</small>
                </p>
                <div className="product-bottom">
                  <div className="product-prices">
                    <strong>{money(p.sale_price)}</strong>
                    {p.list_price !== p.sale_price && (
                      <small className="list-price">{money(p.list_price)}</small>
                    )}
                  </div>
                  <button
                    disabled={busy}
                    onClick={() => {
                      setSelected(p.sku_code);
                      setNotice("Selected " + p.name);
                    }}
                  >
                    {selected === p.sku_code ? "Selected ✓" : "Discuss ↗"}
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
        <aside className="chatpanel">
          <div className="chat-header">
            <div className="avatar">✦</div>
            <div className="chat-title">
              <h2>Your sales advisor</h2>
              <span>
                {status === "handed_off"
                  ? "Human team · waiting for reply"
                  : identified
                    ? "Customer verified · context enabled"
                    : "AI assistant · anonymous session"}
              </span>
            </div>
            <button
              className="call-button"
              disabled={busy || status === "closed" || call !== null}
              title="Gọi thoại với trợ lý trên phiên này"
              onClick={() => {
                // The audio context must be created inside the click (Safari).
                const line = new VoiceCall().prepare();
                action(async () => {
                  try {
                    if (!session) await start();
                    setCall(line);
                  } catch (e) {
                    line.stop();
                    throw e;
                  }
                });
              }}
            >
              ☏ Gọi cửa hàng
            </button>
          </div>
          <div className="chat-context">
            {selected
              ? `Discussing ${selected}`
              : "Choose a product or tell us what you need."}
            <button
              disabled={busy}
              onClick={() => setIdentityOpen(!identityOpen)}
            >
              {identified ? "Identity ✓" : "Remember me"}
            </button>
          </div>
          {identityOpen && (
            <form
              className="identity-form"
              onSubmit={(e) => {
                e.preventDefault();
                action(async () => {
                  if (!session) {
                    await start();
                    setNotice(
                      "Session ready. Submit your number again to verify.",
                    );
                    return;
                  }
                  if (!challenge) {
                    setChallenge(
                      await api(
                        `/api/conversations/${session.conversation_id}/identity/challenge`,
                        session.conversation_token,
                        { kind: "phone", value: phone, consent },
                      ),
                    );
                  } else {
                    const result = await api<{ customer_token: string }>(
                      `/api/conversations/${session.conversation_id}/identity/verify`,
                      session.conversation_token,
                      {
                        challenge_id: challenge.challenge_id,
                        code,
                        customer_token:
                          localStorage.getItem("customer-token") || "",
                      },
                    );
                    localStorage.setItem(
                      "customer-token",
                      result.customer_token,
                    );
                    setIdentified(true);
                    setIdentityOpen(false);
                    setChallenge(null);
                    setNotice(
                      "Identity verified. Your access token is saved on this device.",
                    );
                  }
                });
              }}
            >
              <label>
                Phone number
                <input
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="0901234567"
                  required
                />
              </label>
              <label className="check">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />{" "}
                I consent to identity linking and saving useful preferences.
              </label>
              {challenge && (
                <>
                  <p className="hint">
                    Development code:{" "}
                    {challenge.development_code || "Check your messages"}
                  </p>
                  <input
                    aria-label="Verification code"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    placeholder="6-digit verification code"
                    required
                  />
                </>
              )}
              <button disabled={busy || !consent} type="submit">
                {challenge ? "Verify identity" : "Request verification"}
              </button>
            </form>
          )}
          <div className="messages" aria-live="polite">
            {messages.length === 0 && (
              <div className="welcome">
                <span>✦</span>
                <h3>Let’s find a good fit.</h3>
                <p>
                  Tell me your budget and what you’ll use it for. I can check
                  today’s price and availability.
                </p>
                <button
                  onClick={() =>
                    setText("Em có laptop nào tầm 20 triệu để code không?")
                  }
                >
                  Laptop để code, tầm 20 triệu ↗
                </button>
              </div>
            )}
            {messages.map((m, i) => (
              <div
                key={i}
                className={
                  "message " +
                  (m.speaker === "customer" ? "outgoing" : "incoming")
                }
              >
                <small>
                  {m.speaker === "customer"
                    ? "YOU"
                    : m.speaker === "agent"
                      ? "SALES TEAM"
                      : "AI ADVISOR"}
                </small>
                <p>{m.text || "Thinking…"}</p>
              </div>
            ))}
            <div ref={bottom} />
          </div>
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <textarea
              aria-label="Message"
              rows={2}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Ask a question…"
              disabled={busy || status === "closed"}
            />
            <button
              type="submit"
              disabled={busy || !text.trim() || status === "closed"}
            >
              {busy ? "…" : "Send ↗"}
            </button>
          </form>
          <div className="chat-actions">
            <button
              disabled={busy || !selected || !identified || status !== "open"}
              onClick={() =>
                action(async () => {
                  setQuote(await api<Quote>(`/api/catalog/${selected}/quote`));
                  setConfirmed(false);
                  orderKey.current = crypto.randomUUID();
                })
              }
            >
              Place an order
            </button>
            <button
              disabled={busy || !session || status === "closed"}
              onClick={() =>
                action(async () => {
                  if (session)
                    await api(
                      `/api/conversations/${session.conversation_id}/end`,
                      session.conversation_token,
                      {},
                    );
                  setStatus("closed");
                })
              }
            >
              End session
            </button>
            <button disabled={busy} onClick={() => action(start)}>
              New session
            </button>
          </div>
          <p className="privacy-note">
            AI responses use verified catalog data. Your identity is optional.
          </p>
        </aside>
      </div>
      {call && session && (
        <VoiceCallPanel
          call={call}
          conversationId={session.conversation_id}
          token={session.conversation_token}
          onClose={() => {
            setCall(null);
            load(session).catch((e) => setError(e.message));
          }}
        />
      )}
      {quote && (
        <div className="modal-backdrop">
          <form
            className="modal"
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                if (!session) return;
                const order = await api<{ id: string }>(
                  `/api/conversations/${session.conversation_id}/orders`,
                  session.conversation_token,
                  {
                    sku_code: quote.sku_code,
                    quantity: 1,
                    shipping_address: address,
                    expected_unit_price: quote.sale_price,
                    expected_total: quote.total,
                    confirmed,
                    idempotency_key: orderKey.current,
                  },
                );
                setQuote(null);
                setNotice("Order confirmed: " + order.id);
                setProducts(await api<CommerceCatalogItem[]>("/api/catalog"));
              });
            }}
          >
            <p className="eyebrow">REVIEW YOUR ORDER</p>
            <h2>{quote.name}</h2>
            <p>{quote.sku_code}</p>
            <strong className="order-total">{money(quote.total)}</strong>
            <p>Quantity: 1 · Current stock: {quote.available}</p>
            <label>
              Shipping address
              <textarea
                required
                minLength={5}
                value={address}
                onChange={(e) => setAddress(e.target.value)}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />{" "}
              I confirm this SKU, quantity, address and total.
            </label>
            <div className="buttonrow">
              <button disabled={busy || !confirmed} type="submit">
                Confirm order
              </button>
              <button
                type="button"
                className="secondary"
                disabled={busy}
                onClick={() => setQuote(null)}
              >
                Cancel
              </button>
            </div>
          </form>
        </div>
      )}
      <footer>
        <span>tiếp nối · Connected conversations</span>
        <div>
          <button
            disabled={!session || busy}
            onClick={() =>
              action(async () => {
                if (session)
                  await api(
                    `/api/conversations/${session.conversation_id}/feedback`,
                    session.conversation_token,
                    { rating: 5, category: "helpful" },
                  );
                setNotice("Thanks — your feedback was recorded.");
              })
            }
          >
            Leave positive feedback
          </button>
          <button
            disabled={!identified || busy}
            onClick={() => {
              if (
                window.confirm(
                  "Delete your personal data and saved preferences?",
                )
              )
                action(async () => {
                  await api(
                    "/api/customer/data",
                    localStorage.getItem("customer-token") || "",
                    undefined,
                    "DELETE",
                  );
                  localStorage.removeItem("customer-token");
                  sessionStorage.removeItem("conversation");
                  setSession(null);
                  setMessages([]);
                  setIdentified(false);
                  setNotice("Your personal data was deleted.");
                });
            }}
          >
            Delete my data
          </button>
        </div>
      </footer>
    </main>
  );
}
