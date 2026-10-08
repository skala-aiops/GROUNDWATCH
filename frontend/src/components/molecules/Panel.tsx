import type { ComponentProps } from "react";
import { Card } from "../atoms/card";
import { cn } from "../../design-system/cn";
export default function Panel({ className, ...props }: ComponentProps<typeof Card>) {
 return <Card className={cn("gap-0 py-0 shadow-none",className)} {...props} />;
}
