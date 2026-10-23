import type { Metadata, Viewport } from "next";
import React from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Tiếp Nối — Gia dụng, thời trang, mẹ & bé", template: "%s · Tiếp Nối" },
  description: "Mua sắm gia dụng, thời trang và đồ mẹ bé, với trợ lý tư vấn AI 24/7 và đội ngũ nhân viên hỗ trợ.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
