import React from "react";
import Header from "@/components/shop/Header";
import Footer from "@/components/shop/Footer";
import ChatWidget from "@/components/shop/ChatWidget";
import KitMotion from "@/components/shop/KitMotion";
import ShopMain from "@/components/shop/ShopMain";
import "./shop.css";

// The storefront is built on taste-skill's kit (public/assets): its system, cards, motion and layout
// sheets, then site.css with the dealt palette. React hoists the links into <head> in this order.
const KIT = [
  "/assets/system.css", "/assets/ui/cards.css", "/assets/motion/motion.css", "/assets/layout/layout.css",
  "/assets/ui/base.css", "/assets/ui/chat.css", "/assets/site.css",
];

// The hero's words wait for motion.js instead of flashing; the 700ms mark shows them if it is late. The
// storefront is light only (taste-skill keeps the dark grade for tech pages): set before the first paint,
// never stored, so the staff pages still follow the person's own theme.
const ENTER =
  "var h=document.documentElement;h.dataset.theme='light';h.classList.add('m-enter');setTimeout(function(){h.classList.add('m-enter-done')},700)";

export default function ShopLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      {KIT.map((href) => <link key={href} rel="stylesheet" href={href} precedence="kit" />)}
      <script dangerouslySetInnerHTML={{ __html: ENTER }} />
      <Header />
      <ShopMain>{children}</ShopMain>
      <Footer />
      <div className="s-root"><ChatWidget /></div>
      <KitMotion />
    </>
  );
}
