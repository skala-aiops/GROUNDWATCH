import type { ReactNode } from "react";
export default function DashboardLayout({ reduced, children }: { reduced: boolean; children: ReactNode }) {
  return <div className={reduced ? "app reduced" : "app"}>{children}</div>;
}
