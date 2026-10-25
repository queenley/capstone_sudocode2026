// Quivo's logo, from the files in public/logo: `full` is the wordmark (its "Q" is the
// mark), `mark` the "Q" alone, for tight spots.
//
// Both files are one flat colour, so they are drawn as a CSS mask filled with
// `currentColor`: the brand green on light backgrounds (the default, `text-brand`,
// which turns lighter in dark mode) and white on the dark green chrome of the
// footer, the staff sidebar and the staff sign-in — set by the parent's `color`.
import React from "react";

const FILES = {
  full: { src: "/logo/full-logo.svg", ratio: 1138 / 356 },
  mark: { src: "/logo/main.svg", ratio: 379 / 356 },
} as const;

export function Logo({
  variant = "full",
  height = 32,
  className = "",
  title = "Quivo",
}: {
  variant?: keyof typeof FILES;
  height?: number;
  className?: string;
  /** What a screen reader says; "" when the text beside the logo already says it. */
  title?: string;
}) {
  const { src, ratio } = FILES[variant];
  const mask = `url(${src}) center / contain no-repeat`;
  return (
    <span
      className={`brand-logo ${className}`}
      role={title ? "img" : undefined}
      aria-label={title || undefined}
      aria-hidden={title ? undefined : true}
      style={{ height, width: Math.round(height * ratio), mask, WebkitMask: mask }}
    />
  );
}

/** The "Q" alone; kept for the places that drew the old square mark. */
export function LogoMark({ className = "", title = "" }: { className?: string; title?: string }) {
  return <Logo variant="mark" height={40} className={className} title={title} />;
}
