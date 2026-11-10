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
  // A shared link's card: the home page's hero photograph (taste-skill, system.md: Head).
  openGraph: {
    type: "website",
    title: "Quivo: gia dụng, thời trang và đồ mẹ bé, tư vấn bởi AI",
    description: "Trợ lý AI báo giá, tồn kho và khuyến mãi từ chính cửa hàng; giao miễn phí cho đơn từ 2.000.000₫.",
    images: [{ url: "/assets/img/photo-f107853503-1280.webp", width: 1280, height: 963 }],
  },
  twitter: { card: "summary_large_image" },
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
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#0a1511" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    // data-theme is set before hydration by THEME_SCRIPT, so React must not compare it.
    // data-type, data-radius, data-buttons and data-motion are taste-skill's switches (public/assets/system.css):
    // a product page, soft corners, pill buttons, the motion layer on. Only the storefront loads the kit.
    <html lang="vi" data-type="product" data-radius="soft" data-buttons="pill" data-motion="" suppressHydrationWarning>
      <head>
        {/* The icons come from `metadata.icons` above and src/app/favicon.ico. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
        <meta name="site-kind" content="other" />
        <meta name="page-type" content="product" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin=""
        />
        {/* Without the network the page falls back to the system fonts in theme.css. */}
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Work+Sans:wght@400..700&family=JetBrains+Mono:wght@500&display=swap"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
