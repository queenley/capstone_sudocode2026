import Link from "next/link";
import React from "react";
import { Logo } from "@/components/brand/Logo";
import ThemeToggle from "@/components/theme/ThemeToggle";

/** The staff consoles outside the sales and admin shells (/calls, /developer, /agent, /seller): one header. */
const LINKS: { href: string; label: string }[] = [
  { href: "/ban-hang", label: "Bán hàng" },
  { href: "/agent", label: "Hộp thư" },
  { href: "/calls", label: "Cuộc gọi" },
  { href: "/admin", label: "Quản trị" },
  { href: "/developer", label: "Kỹ thuật" },
];

export default function StaffTopbar({ current, children }: { current?: string; children?: React.ReactNode }) {
  return (
    <header className="topbar">
      <Link className="logo" href="/" aria-label="Quivo, về cửa hàng">
        <Logo height={30} title="" />
      </Link>
      <nav aria-label="Điều hướng nhân viên">
        {LINKS.map((link) => (
          <Link key={link.href} href={link.href} aria-current={link.href === current ? "page" : undefined}>
            {link.label}
          </Link>
        ))}
      </nav>
      {children}
      <ThemeToggle />
    </header>
  );
}
