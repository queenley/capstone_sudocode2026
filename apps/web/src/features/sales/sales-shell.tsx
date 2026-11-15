"use client";
// The sales workspace's frame (app/ban-hang/layout.tsx): the sign-in gate, the sidebar with one link per section, the
// top bar with the hand-off bell. The section itself is the route's page (app/ban-hang/<slug>/page.tsx).
//
// Consultants (agent) see the conversations and call-backs, sellers the orders, admins everything: the API decides,
// a section this token may not read says so instead of showing an empty table.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Logo } from "@/components/brand/Logo";
import { StaffGate, useStaffSession } from "@/components/staff/staff-session";
import ThemeToggle from "@/components/theme/ThemeToggle";
import { HandoffBell } from "./handoff-alerts";
import { SALES_PAGES, SalesIcon } from "./nav";
import { SalesProvider, useSales } from "./sales-context";

export default function SalesShell({ children }: { children: React.ReactNode }) {
  const { token, role, signOut } = useStaffSession();
  const pathname = usePathname();
  if (token === null) return null;
  if (!token)
    return (
      <StaffGate
        title="Trang bán hàng"
        text="Đăng nhập bằng tài khoản nhân viên để xem hội thoại, đơn hàng và lịch gọi lại."
        next={pathname || "/ban-hang"}
      />
    );
  return (
    <SalesProvider token={token} role={role}>
      <Frame onSignOut={signOut}>{children}</Frame>
    </SalesProvider>
  );
}

function Frame({ onSignOut, children }: { onSignOut: () => void; children: React.ReactNode }) {
  const { token, role, access, checked, error, waiting, callbacks, openCall } = useSales();
  const pathname = usePathname() || "";
  const visible = SALES_PAGES.filter((p) => !p.needs || access[p.needs]);
  const current = SALES_PAGES.find((p) => pathname.startsWith(p.href)) || SALES_PAGES[0];
  const allowed = !current.needs || access[current.needs];

  return (
    <div className="sl-app">
      <a className="skip-link" href="#sales-content">
        Đến nội dung chính
      </a>
      <aside className="sl-side">
        <Link href="/" className="sl-logo" aria-label="Quivo, về cửa hàng">
          <span>
            <Logo height={28} title="" className="text-on-chrome" />
            <small className="mt-1 block">Bán hàng & chăm sóc khách</small>
          </span>
        </Link>
        <span className="sl-side-label">Bán hàng</span>
        <nav aria-label="Khu vực bán hàng">
          {visible.map((p) => (
            <Link
              key={p.id}
              href={p.href}
              className={current.id === p.id ? "active" : ""}
              aria-current={current.id === p.id ? "page" : undefined}
            >
              <SalesIcon name={p.id} />
              <span>{p.label}</span>
              {p.id === "conversations" && waiting.length > 0 && <span className="sl-dot">{waiting.length}</span>}
              {p.id === "callbacks" && (callbacks?.length || 0) > 0 && <span className="sl-count">{callbacks!.length}</span>}
            </Link>
          ))}
        </nav>
        <span className="sl-side-label">Hệ thống</span>
        <div className="sl-side-foot">
          {(role === "admin" || role === "developer") && (
            <Link href="/developer">
              <SalesIcon name="console" /> Agent Console
            </Link>
          )}
          {role === "admin" && (
            <Link href="/admin">
              <SalesIcon name="admin" /> Quản trị
            </Link>
          )}
          <button onClick={onSignOut}>
            <SalesIcon name="logout" /> Đăng xuất
          </button>
          <div className="sl-side-status">
            <b>Đang trực</b>
            <span>{waiting.length ? waiting.length + " khách chờ" : "Không ai chờ"}</span>
          </div>
        </div>
      </aside>
      <main id="sales-content" className="sl-main" tabIndex={-1}>
        <div className="sl-topbar">
          <div className="sl-topbar-title">
            <h1>{current.label}</h1>
            <small>{current.hint}</small>
          </div>
          <div className="sl-topbar-actions">
            <span className="sl-live" title="Trang tự tải lại dữ liệu mỗi 10 giây">
              Cập nhật mỗi 10 giây
            </span>
            {access.calls && <HandoffBell token={token} onOpen={openCall} />}
            <ThemeToggle />
          </div>
        </div>
        {error && (
          <div className="sl-alert" role="alert">
            {error}
          </div>
        )}
        {!checked ? (
          <p className="sl-muted" role="status">
            Đang tải…
          </p>
        ) : !allowed ? (
          !error && <p className="sl-muted">Tài khoản này không có quyền xem mục {current.label.toLowerCase()}.</p>
        ) : (
          children
        )}
      </main>
    </div>
  );
}
