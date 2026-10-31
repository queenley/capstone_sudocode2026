"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, ChatMessage, CreateCatalogSkuInput } from "@/services/api";
import AdminTools from "./admin-tools";
import AgentConsole from "./agent-console";

type Row = Record<string, unknown>;
type Detail = { brief: Row; messages: ChatMessage[]; memory_timeline: Row[] };
type CatalogProductForm = Pick<
  CreateCatalogSkuInput,
  "name" | "brand" | "category" | "sku_code" | "list_price" | "sale_price" | "stock"
>;
export default function Workspace({ role }: { role: string }) {
  const [token, setToken] = useState("");
  useEffect(() => {
    setToken(sessionStorage.getItem("staff-token") || "");
  }, []);
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [reply, setReply] = useState("");
  const [reviewText, setReviewText] = useState("");
  const [product, setProduct] = useState<CatalogProductForm>({
    name: "",
    brand: "",
    category: "laptop",
    sku_code: "",
    list_price: "0",
    sale_price: "0",
    stock: 0,
  });
  const paths: Record<string, string> = {
    agent: "/api/staff/conversations",
    admin: "/api/admin/proposals",
    seller: "/api/seller/orders",
    developer: "/api/developer/traces",
  };
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  async function refresh() {
    setRows(await api<Row[]>(paths[role], token));
  }
  if (role === "developer") {
    return <AgentConsole token={token} onToken={setToken} />;
  }
  return (
    <main className="shell workspace">
      <header className="topbar">
        <Link className="logo" href="/">
          Quivo
        </Link>
        <nav>
          <Link href="/login">Sign in</Link>
          {["agent", "admin", "seller", "developer"].map((r) => (
            <Link key={r} href={"/" + r}>
              {r}
            </Link>
          ))}
          <Link href="/calls">calls</Link>
        </nav>
      </header>
      <div className="section-heading">
        <div>
          <p className="eyebrow">INTERNAL WORKSPACE</p>
          <h1>
            {role === "agent"
              ? "Every handoff, in context."
              : role === "admin"
                ? "Review. Approve. Improve."
                : role === "seller"
                  ? "From conversation to conversion."
                  : "See what the harness did."}
          </h1>
        </div>
      </div>
      <form
        className="authbar"
        onSubmit={(e) => {
          e.preventDefault();
          action(refresh);
        }}
      >
        <label>
          Staff access token
          <input
            type="password"
            autoComplete="off"
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Enter your role access token"
            required
          />
        </label>
        <button disabled={busy} type="submit">
          Connect / Refresh
        </button>
      </form>
      {error && (
        <div role="alert" className="alert">
          {error}
        </div>
      )}
      {role === "agent" && (
        <div className="notice">
          Cuộc gọi do trợ lý AI chuyển máy (có gợi ý trả lời, brief và bằng chứng) nằm ở{" "}
          <Link href="/calls">
            <strong>console cuộc gọi ↗</strong>
          </Link>
          . Inbox này là hàng chờ của platform.
        </div>
      )}
      <div className="workspace-grid">
        <section className="panel">
          <h2>
            {role === "agent"
              ? "Conversation inbox"
              : role === "admin"
                ? "Improvement proposals"
                : role === "seller"
                  ? "Orders"
                  : "Turn traces"}
          </h2>
          {rows.length === 0 && (
            <p className="empty">
              Connect to load records. New records appear after buyer activity.
            </p>
          )}
          {rows.map((row, i) => (
            <article
              className="record"
              key={String(row.id || row.trace_id || i)}
            >
              <div className="record-title">
                <strong>{String(row.status || row.route || row.kind)}</strong>
                <small>{String(row.id || row.trace_id)}</small>
              </div>
              <pre>{JSON.stringify(row, null, 2)}</pre>
              {role === "agent" && (
                <button
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      const id = String(row.id);
                      setSelected(id);
                      setDetail(
                        await api<Detail>(
                          `/api/staff/conversations/${id}`,
                          token,
                        ),
                      );
                    })
                  }
                >
                  Open brief and conversation ↗
                </button>
              )}
              {role === "seller" && row.status === "confirmed" && (
                <button
                  disabled={busy}
                  onClick={() =>
                    action(async () => {
                      await api(
                        `/api/seller/orders/${row.id}/cancel`,
                        token,
                        {},
                      );
                      await refresh();
                    })
                  }
                >
                  Cancel and release inventory
                </button>
              )}
              {role === "admin" && row.status === "pending" && (
                <div className="buttonrow">
                  <button
                    disabled={busy || !reviewText.trim()}
                    onClick={() =>
                      action(async () => {
                        await api(
                          `/api/admin/proposals/${row.id}/review`,
                          token,
                          { decision: "approved", knowledge_text: reviewText },
                        );
                        setReviewText("");
                        await refresh();
                      })
                    }
                  >
                    Approve reviewed text
                  </button>
                  <button
                    disabled={busy}
                    className="secondary"
                    onClick={() =>
                      action(async () => {
                        await api(
                          `/api/admin/proposals/${row.id}/review`,
                          token,
                          { decision: "rejected" },
                        );
                        await refresh();
                      })
                    }
                  >
                    Reject
                  </button>
                </div>
              )}
            </article>
          ))}
        </section>
        <aside className="panel">
          {role === "agent" ? (
            <>
              <h2>Call brief & memory timeline</h2>
              {detail ? (
                <>
                  <pre>{JSON.stringify(detail.brief, null, 2)}</pre>
                  <h3>Memory provenance</h3>
                  <pre>{JSON.stringify(detail.memory_timeline, null, 2)}</pre>
                  <div className="messages staff-messages">
                    {detail.messages.map((m, i) => (
                      <div className="message incoming" key={i}>
                        <small>{m.speaker}</small>
                        <p>{m.text}</p>
                      </div>
                    ))}
                  </div>
                  <div className="buttonrow">
                    <button
                      disabled={busy}
                      onClick={() =>
                        action(async () => {
                          await api(
                            `/api/staff/conversations/${selected}/claim`,
                            token,
                            {},
                          );
                          await refresh();
                        })
                      }
                    >
                      Claim handoff
                    </button>
                    <button
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        action(async () =>
                          setDetail(
                            await api<Detail>(
                              `/api/staff/conversations/${selected}`,
                              token,
                            ),
                          ),
                        )
                      }
                    >
                      Refresh messages
                    </button>
                  </div>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      action(async () => {
                        await api(
                          `/api/staff/conversations/${selected}/messages`,
                          token,
                          { message: reply },
                        );
                        setReply("");
                        setDetail(
                          await api<Detail>(
                            `/api/staff/conversations/${selected}`,
                            token,
                          ),
                        );
                      });
                    }}
                  >
                    <label>
                      Reply as a human
                      <textarea
                        required
                        value={reply}
                        onChange={(e) => setReply(e.target.value)}
                      />
                    </label>
                    <button disabled={busy} type="submit">
                      Send reply
                    </button>
                  </form>
                </>
              ) : (
                <p>Select a conversation to see its structured brief.</p>
              )}
            </>
          ) : role === "admin" ? (
            <>
              <h2>Reviewed knowledge</h2>
              <p>
                Write the verified answer before approving a proposal.
                Unreviewed conversations never become production knowledge
                automatically.
              </p>
              <textarea
                aria-label="Reviewed knowledge"
                rows={6}
                value={reviewText}
                onChange={(e) => setReviewText(e.target.value)}
              />
              <h2>Add catalog product</h2>
              <AdminTools token={token} onError={setError} />
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  action(async () => {
                    await api("/api/admin/catalog", token, product);
                    setError("Product created.");
                  });
                }}
              >
                {Object.entries(product).map(([key, value]) => (
                  <label key={key}>
                    {key.replaceAll("_", " ")}
                    <input
                      required
                      type={
                        ["stock", "list_price", "sale_price"].includes(key)
                          ? "number"
                          : "text"
                      }
                      min="0"
                      value={value}
                      onChange={(e) =>
                        setProduct((old) => ({
                          ...old,
                          [key]:
                            key === "stock"
                              ? Number(e.target.value)
                              : e.target.value,
                        }))
                      }
                    />
                  </label>
                ))}
                <button disabled={busy} type="submit">
                  Create product
                </button>
              </form>
            </>
          ) : role === "seller" ? (
            <>
              <h2>Sales overview</h2>
              <div className="stat">
                <strong>
                  {rows.filter((r) => r.status === "confirmed").length}
                </strong>
                <span>Confirmed orders in this view</span>
              </div>
              <div className="stat">
                <strong>
                  {new Intl.NumberFormat("vi-VN").format(
                    rows
                      .filter((r) => r.status !== "cancelled")
                      .reduce((sum, r) => sum + Number(r.total || 0), 0),
                  )}{" "}
                  ₫
                </strong>
                <span>Order value in this view</span>
              </div>
              <p>
                Totals cover the most recent 100 orders. Cancelled orders
                release reserved inventory once.
              </p>
            </>
          ) : (
            <>
              <h2>Routing & performance</h2>
              <div className="stat">
                <strong>{rows.length}</strong>
                <span>Recent traces</span>
              </div>
              <p>
                Each turn records route confidence, latency, token usage and
                tool execution. Run the evaluation command to compare baseline
                against cross-session memory.
              </p>
              <pre>python evaluation/rag_offline.py</pre>
            </>
          )}
        </aside>
      </div>
    </main>
  );
}
