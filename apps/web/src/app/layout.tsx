import type { Metadata, Viewport } from "next";
import React from "react";
import { THEME_SCRIPT } from "@/components/theme/ThemeToggle";
import "./theme.css";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Tiếp Nối — Gia dụng, thời trang, mẹ & bé", template: "%s · Tiếp Nối" },
  description: "Mua sắm gia dụng, thời trang và đồ mẹ bé, với trợ lý tư vấn AI 24/7 và đội ngũ nhân viên hỗ trợ.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#065f46" },
    { media: "(prefers-color-scheme: dark)", color: "#0a1a15" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // data-theme is set before hydration by THEME_SCRIPT, so React must not compare it.
    <html lang="vi" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* Without the network the page falls back to the system fonts in theme.css. */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
