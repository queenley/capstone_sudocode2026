import type { Metadata, Viewport } from "next";
import React from "react";
import { THEME_SCRIPT } from "@/components/theme/ThemeToggle";
import "./theme.css";
import "./globals.css";
import "./tailwind.css";

export const metadata: Metadata = {
  title: {
    default: "Quivo — Gia dụng, thời trang, mẹ & bé",
    template: "%s · Quivo",
  },
  description:
    "Mua sắm gia dụng, thời trang và đồ mẹ bé, với trợ lý tư vấn AI 24/7 và đội ngũ nhân viên hỗ trợ.",
  applicationName: "Quivo",
  // favicon.ico sits in src/app (Next serves it); the rest are in public/.
  icons: {
    icon: [
      { url: "/favicon-32x32.png", sizes: "32x32", type: "image/png" },
      { url: "/favicon-16x16.png", sizes: "16x16", type: "image/png" },
    ],
    apple: { url: "/apple-touch-icon.png", sizes: "180x180" },
  },
  manifest: "/site.webmanifest",
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
        {/* The icons come from `metadata.icons` above and src/app/favicon.ico. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin=""
        />
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
