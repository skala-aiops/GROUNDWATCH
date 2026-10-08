import { Badge as StatusBadge } from "../atoms/badge";
import { label } from "../../utils/format";
export default function Badge({ status }: { status: unknown }) {
  return (
    <StatusBadge variant="outline" className={"badge " + String(status || "pending").toLowerCase()}>
      {label(status)}
    </StatusBadge>
  );
}
