// The shop's mark: a headset on emerald, after the "Harness Emerald Logo".
// The same in both themes, as a brand mark should be.
export function LogoMark({ className = "", title }: { className?: string; title?: string }) {
  return (
    <svg className={className} viewBox="0 0 40 40" role={title ? "img" : undefined} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <rect width="40" height="40" rx="10" fill="#059669" />
      <path d="M11.5 22v-2.5a8.5 8.5 0 0 1 17 0V22" fill="none" stroke="#fff" strokeWidth="3.2" strokeLinecap="round" />
      <path d="M28.5 22v2.5a4 4 0 0 1-4 4h-3" fill="none" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="12" cy="23" r="3.6" fill="#34d399" />
      <circle cx="28" cy="23" r="3.6" fill="#34d399" />
    </svg>
  );
}
