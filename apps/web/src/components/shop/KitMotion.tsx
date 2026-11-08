"use client";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

// taste-skill's motion layer and the page's dealt moment (public/assets/motion, public/assets/moments).
// Both start themselves on a static page; here the pages change without a reload, so motion.js is
// refreshed and the moments mounted again after each route, and unmounted when it leaves.
const MOTION = "/assets/motion/motion.js";
const MOMENTS = "/assets/moments/moments.js";

// The kit's modules are plain files under public/, loaded by the browser as they are: the bundler must
// never see these imports (a dynamic import of a variable makes it try to bundle a whole folder).
// eslint-disable-next-line @typescript-eslint/no-implied-eval
const load = new Function("url", "return import(url)") as (url: string) => Promise<unknown>;

type Motion = { refresh?: () => void };
type Moments = { mountAll: (root?: Document) => Promise<unknown>; unmountAll: (root?: Document) => void };

export default function KitMotion() {
  const pathname = usePathname();

  useEffect(() => {
    let gone = false;
    let moments: Moments | null = null;
    (async () => {
      const motion = (await load(MOTION)) as Motion;
      if (gone) return;
      motion.refresh?.();
      if (!document.querySelector("[data-moment]")) return;
      (window as unknown as { __momentsManual?: boolean }).__momentsManual = true;
      moments = (await load(MOMENTS)) as Moments;
      if (!gone) await moments?.mountAll(document);
    })().catch(() => {
      // Without the layer the page stands as written: the moments show their finished state.
      document.documentElement.classList.add("m-enter-done", "mo-safe");
    });
    return () => {
      gone = true;
      moments?.unmountAll(document);
    };
  }, [pathname]);

  return null;
}
