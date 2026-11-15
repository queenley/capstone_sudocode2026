"use client";
// The admin workspace's frame (app/admin/layout.tsx), apart from the sales team's (/ban-hang): the sign-in gate, the
// sidebar with one link per section, the top bar and the notice line. The section itself is the route's page
// (app/admin/<slug>/page.tsx). docs/plan/001-vong-cai-tien-hang-tuan-va-dashboard.md, part A.
//
// Every section asks the API, which refuses any role but admin (403): the page never decides access on its own.
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Logo } from "@/components/brand/Logo";
import { StaffGate, useStaffSession } from "@/components/staff/staff-session";
import ThemeToggle from "@/components/theme/ThemeToggle";
import { AdminContext } from "./admin-context";
import { ADMIN_PAGES, AdminIcon } from "./nav";

export default function AdminShell({ children }: { children: React.ReactNode }) {
  const { token, signOut } = useStaffSession();
  const pathname = usePathname() || "";
  const [notice, setNotice] = useState("");
  const shared = useMemo(() => ({ token: token || "", notice, setNotice }), [token, notice]);

  // A notice belongs to the section it was raised in.
  useEffect(() => setNotice(""), [pathname]);

  if (token === null) return null;
  if (!token)
    return (
      <StaffGate
        title="Trang quản trị"
        text="Đăng nhập bằng tài khoản quản trị để duyệt kiến thức, đề xuất cải tiến, sản phẩm và nhân sự."
        next={pathname || "/admin"}
      />
    );

  const current = ADMIN_PAGES.find((p) => pathname.startsWith(p.href)) || ADMIN_PAGES[0];
  const ok = /^Đã /.test(notice);
  return (
    <AdminContext.Provider value={shared}>
      <div className="sl-app ad-app">
        <a className="skip-link" href="#admin-content">
          Đến nội dung chính
        </a>
        <aside className="sl-side">
          <Link href="/" className="sl-logo" aria-label="Quivo, về cửa hàng">
            <span>
              <Logo height={28} title="" className="text-on-chrome" />
              <small className="mt-1 block">Quản trị</small>
            </span>
          </Link>
          <span className="sl-side-label">Quản trị</span>
          <nav aria-label="Khu vực quản trị">
            {ADMIN_PAGES.map((p) => (
              <Link
                key={p.id}
                href={p.href}
                className={current.id === p.id ? "active" : ""}
                aria-current={current.id === p.id ? "page" : undefined}
              >
                <AdminIcon name={p.id} />
                <span>{p.label}</span>
              </Link>
            ))}
          </nav>
          <span className="sl-side-label">Trang khác</span>
          <div className="sl-side-foot">
            <Link href="/ban-hang">
              <AdminIcon name="sales" /> Trang bán hàng
            </Link>
            <Link href="/developer">
              <AdminIcon name="console" /> Agent Console
            </Link>
            <button onClick={signOut}>
              <AdminIcon name="logout" /> Đăng xuất
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
          {/* One line for both outcomes: a confirmation reads as one, not as an error. */}
          {notice && (
            <div className={ok ? "sl-alert ad-ok" : "sl-alert"} role={ok ? "status" : "alert"}>
              {notice}
            </div>
          )}
          {children}
        </main>
      </div>
    </AdminContext.Provider>
  );
}
