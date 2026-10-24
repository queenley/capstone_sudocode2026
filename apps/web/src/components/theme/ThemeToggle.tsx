"use client";
// Light, dark, or the system's: one button cycles through them. The choice is
// kept in localStorage ("theme") and set as <html data-theme>; with none set,
// theme.css follows prefers-color-scheme. THEME_SCRIPT applies a saved choice
// before the first paint, so a dark page never flashes white.
import { useEffect, useState } from "react";

type Theme = "system" | "light" | "dark";
const KEY = "theme";
const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<Theme, string> = {
  system: "Giao diện: theo hệ thống",
  light: "Giao diện: sáng",
  dark: "Giao diện: tối",
};

/** Inline in <head> (app/layout.tsx): runs before React, so it is a string. */
export const THEME_SCRIPT = `try{var t=localStorage.getItem("${KEY}");if(t==="light"||t==="dark")document.documentElement.dataset.theme=t}catch(e){}`;

function saved(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === "light" || value === "dark" ? value : "system";
  } catch {
    return "system";
  }
}

function apply(theme: Theme) {
  const root = document.documentElement;
  if (theme === "system") delete root.dataset.theme;
  else root.dataset.theme = theme;
  try {
    if (theme === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    /* private mode: the choice lasts for this page */
  }
}

export default function ThemeToggle({ onChrome = false }: { onChrome?: boolean }) {
  // "system" on the server and the first render, then the saved choice.
  const [theme, setTheme] = useState<Theme>("system");
  useEffect(() => setTheme(saved()), []);

  return (
    <button
      type="button"
      className={"theme-toggle" + (onChrome ? " on-chrome" : "")}
      onClick={() => {
        const next = NEXT[theme];
        apply(next);
        setTheme(next);
      }}
      title={LABEL[theme] + " (bấm để đổi)"}
      aria-label={LABEL[theme] + ". Bấm để đổi"}
    >
      {theme === "light" ? <Sun /> : theme === "dark" ? <Moon /> : <Auto />}
    </button>
  );
}

const svg = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };

function Sun() {
  return (
    <svg {...svg}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41" />
    </svg>
  );
}

function Moon() {
  return (
    <svg {...svg}>
      <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
    </svg>
  );
}

function Auto() {
  return (
    <svg {...svg}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" stroke="none" />
    </svg>
  );
}
