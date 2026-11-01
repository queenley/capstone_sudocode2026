import React from "react";
import Header from "@/components/shop/Header";
import Footer from "@/components/shop/Footer";
import ChatWidget from "@/components/shop/ChatWidget";
import "./shop.css";

export default function ShopLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="s-root">
      <a className="skip-link" href="#shop-content">Đến nội dung chính</a>
      <Header />
      <main id="shop-content" className="s-main" tabIndex={-1}>{children}</main>
      <Footer />
      <ChatWidget />
    </div>
  );
}
