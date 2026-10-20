import type { ReactNode } from "react";
import { Database, KeyRound, Server } from "lucide-react";
import type { ServiceStatus } from "../lib/api";
import { bytes, percent, uptime } from "../lib/format";
import { Sparkline } from "./Sparkline";
import { StateBadge } from "./StateBadge";
import { Callout, Card, Stat } from "./ui";

const ICONS: Record<string, ReactNode> = {
  world: <Server className="size-4" />,
  auth: <KeyRound className="size-4" />,
  mysql: <Database className="size-4" />,
};

/** Detailed service card used on Server Control (stats, CPU sparkline, error message, controls). */
export function ServiceDetailCard({ s, children }: { s: ServiceStatus; children?: ReactNode }) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold">
          <span className="text-muted">{ICONS[s.key]}</span>
          {s.label}
        </div>
        <StateBadge state={s.state} />
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        <Stat label="PID" value={s.pid ?? "—"} mono />
        <Stat label="Uptime" value={uptime(s.started_at)} mono />
        <Stat label="CPU" value={percent(s.cpu)} mono />
        <Stat label="Memory" value={bytes(s.memory)} mono />
      </div>
      <div className="mt-3">
        <Sparkline values={s.history.map((h) => h.cpu)} max={5} color={s.key === "world" ? "var(--accent)" : "var(--ok)"} />
      </div>
      {s.message && (
        <div className="mt-3">
          <Callout tone="bad">{s.message}</Callout>
        </div>
      )}
      {children}
    </Card>
  );
}
