// The staff consoles of /agent, /seller and /developer. The developer console embeds the admin's evaluation
// dashboard (features/admin/evaluation-dashboard.tsx), so it loads the same staff and admin styles; live.css is
// the live view (features/developer/live-monitor.tsx). Every rule in these files is class-scoped.
import "../ban-hang/sales.css";
import "../admin/admin.css";
import "./live.css";

export default function RoleLayout({ children }: { children: React.ReactNode }) {
  return children;
}
