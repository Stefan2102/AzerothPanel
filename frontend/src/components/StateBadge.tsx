import type { ServiceState } from "../lib/api";
import { Badge } from "./ui";

const MAP: Record<ServiceState, { tone: "ok" | "bad" | "warn" | "accent" | "muted"; label: string; pulse?: boolean }> = {
  running: { tone: "ok", label: "Online" },
  external: { tone: "ok", label: "Online (external)" },
  starting: { tone: "warn", label: "Starting", pulse: true },
  stopping: { tone: "warn", label: "Stopping", pulse: true },
  stopped: { tone: "bad", label: "Offline" },
};

export function StateBadge({ state }: { state: ServiceState }) {
  const s = MAP[state];
  return (
    <Badge tone={s.tone} dot pulse={s.pulse}>
      {s.label}
    </Badge>
  );
}

export const isUp = (s: ServiceState) => s === "running" || s === "external";
