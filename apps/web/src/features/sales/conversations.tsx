"use client";
// /ban-hang/hoi-thoai: the live console, inside the workspace (already signed in); the bell's call opens here.
import CallConsole from "./call-console";
import { useSales } from "./sales-context";

export default function Conversations() {
  const { focus } = useSales();
  return (
    <div className="sl-console">
      <CallConsole embedded focus={focus} />
    </div>
  );
}
