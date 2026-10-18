import { AlertTriangle, Info } from "lucide-react";

import { cn } from "@/lib/utils";

export function Alert({
  tone = "info",
  title,
  children,
}: {
  tone?: "info" | "warning" | "error";
  title?: string;
  children?: React.ReactNode;
}) {
  const styles = {
    info: "border-blue-200 bg-blue-50 text-blue-900",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    error: "border-red-200 bg-red-50 text-red-900",
  }[tone];
  const Icon = tone === "info" ? Info : AlertTriangle;
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn("flex gap-3 rounded-lg border p-3", styles)}
    >
      <Icon aria-hidden className="mt-0.5 h-5 w-5 shrink-0" />
      <div className="text-sm">
        {title && <p className="font-semibold">{title}</p>}
        {children}
      </div>
    </div>
  );
}
