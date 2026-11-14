"use client";
import { usePathname } from "next/navigation";
import React from "react";

// The home page is a stack of screens: its sections sit directly in <main>, where the kit makes each one
// or two screens tall. Every other storefront page is an app page and keeps its own height, so it is
// wrapped once (.s-app, public/assets/site.css) and the kit's `main > section` rule never reaches it.
export default function ShopMain({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const home = pathname === "/";
  // Keyed by the path, so each page enters once (shop.css, "motion: the storefront's own").
  return (
    <main id="shop-content" className="s-main" tabIndex={-1}>
      {home ? children : <div key={pathname} className="s-app s-root s-route">{children}</div>}
    </main>
  );
}
