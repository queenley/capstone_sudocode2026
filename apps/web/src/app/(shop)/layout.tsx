import React from "react";
import Header from "@/components/shop/Header";
import Footer from "@/components/shop/Footer";
import ChatWidget from "@/components/shop/ChatWidget";
import "./shop.css";

export default function ShopLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="s-root">
      <Header />
      <main className="s-main">{children}</main>
      <Footer />
      <ChatWidget />
    </div>
  );
}
