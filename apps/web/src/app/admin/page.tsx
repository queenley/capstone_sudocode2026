"use client";
// The admin's workspace, apart from the sales team's (/ban-hang): what the assistant knows, the proposals waiting
// for a person, the catalogue and the staff accounts. docs/plan/001-vong-cai-tien-hang-tuan-va-dashboard.md, part A.
//
// Sign-in is the staff login (/login), whose token is in sessionStorage ("staff-token"). Every section asks the API,
// which refuses any role but admin (403): the page never decides access on its own.
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Logo } from "@/components/brand/Logo";
import ThemeToggle from "@/components/theme/ThemeToggle";
import AdminTools from "@/features/admin-tools";
import EvaluationDashboard from "@/features/evaluation-dashboard";
import FaqAdmin from "@/features/faq-admin";
import ImprovementAdmin from "@/features/improvement-admin";
import KnowledgeGaps from "@/features/knowledge-gaps";
import { api } from "@/services/api";
import "../ban-hang/sales.css";
import "./admin.css";

type Tab = "knowledge" | "improvement" | "evaluation" | "proposals" | "catalog" | "staff";
type Proposal = { id: string; kind: string; candidate: unknown; status: string };
type Product = {
  name: string;
  brand: string;
  category: string;
  sku_code: string;
  list_price: string;
  sale_price: string;
  stock: number;
};

const svg = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
const ICONS = {
  knowledge: <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5zM4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5" />,
  proposals: <path d="M9 11l3 3 8-8M20 12v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h9" />,
  improvement: <path d="M21 12a9 9 0 1 1-3-6.7M21 4v5h-5" />,
  evaluation: <path d="M3 3v18h18M7 15l4-4 3 3 5-6" />,
  catalog: <path d="M21 16V8l-9-5-9 5v8l9 5zM3.3 7L12 12l8.7-5M12 22V12" />,
  staff: <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM23 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8" />,
  sales: <path d="M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z" />,
  console: <path d="M4 17l6-6-6-6M12 19h8" />,
  logout: <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" />,
};
const Icon = ({ name }: { name: keyof typeof ICONS }) => <svg {...svg}>{ICONS[name]}</svg>;

const TABS: { id: Tab; label: string; hint: string }[] = [
  { id: "knowledge", label: "Kiến thức", hint: "Câu khách hỏi mà tài liệu chưa có, và FAQ chờ duyệt" },
  { id: "improvement", label: "Cải tiến hằng tuần", hint: "Đề xuất của Reflection mỗi tuần: duyệt, xem phép đo, rồi mới bật" },
  { id: "evaluation", label: "Đánh giá", hint: "Chỉ số BTC theo từng tuần, cùng bộ kịch bản và cùng extractor" },
  { id: "proposals", label: "Đề xuất từ hội thoại", hint: "Đề xuất từ hội thoại; chỉ thành kiến thức khi có người duyệt" },
  { id: "catalog", label: "Sản phẩm", hint: "Thêm sản phẩm vào catalog" },
  { id: "staff", label: "Nhân sự & kho", hint: "Tài khoản nhân viên, tồn kho, khuyến mãi" },
];
const STATUS: Record<string, string> = { pending: "Chờ duyệt", approved: "Đã duyệt", rejected: "Đã từ chối" };
const PRODUCT_FIELDS: { key: keyof Product; label: string; type: "text" | "number" }[] = [
  { key: "name", label: "Tên sản phẩm", type: "text" },
  { key: "brand", label: "Thương hiệu", type: "text" },
  { key: "category", label: "Danh mục", type: "text" },
  { key: "sku_code", label: "Mã SKU", type: "text" },
  { key: "list_price", label: "Giá niêm yết (đ)", type: "number" },
  { key: "sale_price", label: "Giá bán (đ)", type: "number" },
  { key: "stock", label: "Tồn kho", type: "number" },
];
const EMPTY_PRODUCT: Product = { name: "", brand: "", category: "laptop", sku_code: "", list_price: "0", sale_price: "0", stock: 0 };

export default function AdminPage() {
  const [token, setToken] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("knowledge");
  const [notice, setNotice] = useState("");
  const [faqAdded, setFaqAdded] = useState(0);

  useEffect(() => {
    setToken(sessionStorage.getItem("staff-token") || "");
    const wanted = new URLSearchParams(window.location.search).get("tab") as Tab | null;
    if (wanted && TABS.some((t) => t.id === wanted)) setTab(wanted);
  }, []);

  function go(next: Tab) {
    setTab(next);
    setNotice("");
    window.history.replaceState(null, "", `/admin?tab=${next}`);
  }

  if (token === null) return null;
  if (!token)
    return (
      <div className="sl-gate">
        <div className="sl-gate-card">
          <Logo height={40} className="text-brand" />
          <h1>Trang quản trị</h1>
          <p>Đăng nhập bằng tài khoản quản trị để duyệt kiến thức, đề xuất cải tiến, sản phẩm và nhân sự.</p>
          <Link className="sl-btn" href="/login?next=/admin">
            Đăng nhập
          </Link>
        </div>
      </div>
    );

  const current = TABS.find((t) => t.id === tab) || TABS[0];
  return (
    <div className="sl-app">
      <a className="skip-link" href="#admin-content">Đến nội dung chính</a>
      <aside className="sl-side">
        <Link href="/" className="sl-logo" aria-label="Quivo, về cửa hàng">
          <span>
            <Logo height={28} title="" className="text-on-chrome" />
            <small className="mt-1 block">Quản trị</small>
          </span>
        </Link>
        <span className="sl-side-label">Quản trị</span>
        <nav aria-label="Khu vực quản trị">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={tab === t.id ? "active" : ""}
              onClick={() => go(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
            >
              <Icon name={t.id} />
              <span>{t.label}</span>
            </button>
          ))}
        </nav>
        <span className="sl-side-label">Trang khác</span>
        <div className="sl-side-foot">
          <Link href="/ban-hang">
            <Icon name="sales" /> Trang bán hàng
          </Link>
          <Link href="/developer">
            <Icon name="console" /> Agent Console
          </Link>
          <button
            onClick={() => {
              sessionStorage.removeItem("staff-token");
              sessionStorage.removeItem("staff-role");
              setToken("");
            }}
          >
            <Icon name="logout" /> Đăng xuất
          </button>
        </div>
      </aside>
      <main id="admin-content" className="sl-main" tabIndex={-1}>
        <div className="sl-topbar">
          <div className="sl-topbar-title">
            <h1>{current.label}</h1>
            <small>{current.hint}</small>
          </div>
          <div className="sl-topbar-actions">
            <ThemeToggle />
          </div>
        </div>
        {notice && <div className="sl-alert" role="alert">{notice}</div>}
        {tab === "knowledge" ? (
          <div className="sl-columns">
            <KnowledgeGaps token={token} onFaqCreated={() => setFaqAdded((count) => count + 1)} />
            <FaqAdmin token={token} refresh={faqAdded} />
          </div>
        ) : tab === "improvement" ? (
          <ImprovementAdmin token={token} onNotice={setNotice} />
        ) : tab === "evaluation" ? (
          <EvaluationDashboard token={token} onNotice={setNotice} />
        ) : tab === "proposals" ? (
          <Proposals token={token} onNotice={setNotice} />
        ) : tab === "catalog" ? (
          <Catalog token={token} onNotice={setNotice} />
        ) : (
          <section className="sl-panel" aria-label="Nhân sự và kho">
            <AdminTools token={token} onError={setNotice} />
          </section>
        )}
      </main>
    </div>
  );
}

function Proposals({ token, onNotice }: { token: string; onNotice: (text: string) => void }) {
  const [rows, setRows] = useState<Proposal[] | null>(null);
  const [texts, setTexts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api<Proposal[]>("/api/admin/proposals", token));
    } catch (e) {
      setRows([]);
      onNotice(e instanceof Error ? e.message : "Không tải được đề xuất");
    }
  }, [token, onNotice]);

  useEffect(() => {
    load();
  }, [load]);

  async function decide(id: string, decision: "approved" | "rejected") {
    setBusy(true);
    try {
      await api(`/api/admin/proposals/${id}/review`, token,
        decision === "approved" ? { decision, knowledge_text: texts[id] || "" } : { decision });
      onNotice(decision === "approved" ? "Đã duyệt đề xuất." : "Đã từ chối đề xuất.");
      await load();
    } catch (e) {
      onNotice(e instanceof Error ? e.message : "Không lưu được quyết định");
    } finally {
      setBusy(false);
    }
  }

  if (rows === null) return <p className="sl-muted" role="status">Đang tải…</p>;
  if (rows.length === 0) return <p className="sl-muted">Chưa có đề xuất nào.</p>;
  return (
    <div className="sl-columns">
      {rows.map((row) => (
        <article className="sl-panel" key={row.id} aria-label={`Đề xuất ${row.id}`}>
          <header>
            <strong>{row.kind}</strong>
            <span className="sl-badge">{STATUS[row.status] || row.status}</span>
          </header>
          <pre className="sl-code">{JSON.stringify(row.candidate, null, 2)}</pre>
          {row.status === "pending" && (
            <>
              <label>
                Nội dung kiến thức đã kiểm tra
                <textarea
                  rows={4}
                  value={texts[row.id] || ""}
                  onChange={(e) => setTexts((old) => ({ ...old, [row.id]: e.target.value }))}
                />
              </label>
              <div className="sl-actions">
                <button
                  className="sl-btn sl-btn-small"
                  disabled={busy || !(texts[row.id] || "").trim()}
                  onClick={() => decide(row.id, "approved")}
                >
                  Duyệt nội dung đã kiểm tra
                </button>
                <button className="sl-btn sl-btn-small sl-danger" disabled={busy} onClick={() => decide(row.id, "rejected")}>
                  Từ chối
                </button>
              </div>
            </>
          )}
        </article>
      ))}
    </div>
  );
}

function Catalog({ token, onNotice }: { token: string; onNotice: (text: string) => void }) {
  const [product, setProduct] = useState<Product>(EMPTY_PRODUCT);
  const [busy, setBusy] = useState(false);
  return (
    <form
      className="sl-panel"
      aria-label="Thêm sản phẩm"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        try {
          await api("/api/admin/catalog", token, product);
          onNotice("Đã thêm sản phẩm.");
          setProduct(EMPTY_PRODUCT);
        } catch (error) {
          onNotice(error instanceof Error ? error.message : "Không thêm được sản phẩm");
        } finally {
          setBusy(false);
        }
      }}
    >
      {PRODUCT_FIELDS.map(({ key, label, type }) => (
        <label key={key}>
          {label}
          <input
            required
            type={type}
            min={type === "number" ? "0" : undefined}
            value={product[key]}
            onChange={(e) =>
              setProduct((old) => ({ ...old, [key]: key === "stock" ? Number(e.target.value) : e.target.value }))
            }
          />
        </label>
      ))}
      <button className="sl-btn" disabled={busy} type="submit">
        Thêm sản phẩm
      </button>
    </form>
  );
}
