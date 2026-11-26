import React from "react";

/** A storefront page with nothing to show yet (an empty cart, nothing to check out, an error): a heading, one line
    that says what to do, the actions, and whatever the page adds under them (shop.css, "empty states"). */
export default function EmptyState({
  title,
  line,
  actions,
  children,
  alert = false,
}: {
  title: string;
  line: string;
  actions: React.ReactNode;
  children?: React.ReactNode;
  alert?: boolean;
}) {
  return (
    <div className="s-wrap s-page s-empty-state" role={alert ? "alert" : undefined}>
      <h1 className="s-page-title">{title}</h1>
      <p>{line}</p>
      <div className="s-center">{actions}</div>
      {children}
    </div>
  );
}
