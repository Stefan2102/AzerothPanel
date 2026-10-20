import type { ReactNode } from "react";
import { Activity, FileCog, HardDrive, Play, ScrollText, Server, Users } from "lucide-react";
import type { ServiceStatus } from "../lib/api";
import { uptime } from "../lib/format";
import { useStatus } from "../lib/hooks";
import { StateBadge } from "../components/StateBadge";
import { Card, PageHeader, Stat } from "../components/ui";

const QUICK_ACTIONS = [
  { to: "/server", icon: <Play className="size-4" />, label: "Server Control", desc: "Start, stop or restart servers" },
  { to: "/logs", icon: <ScrollText className="size-4" />, label: "Logs", desc: "Live worldserver & auth logs" },
  { to: "/players", icon: <Users className="size-4" />, label: "Players", desc: "Online characters & accounts" },
  { to: "/configs", icon: <FileCog className="size-4" />, label: "Config Files", desc: "Edit .conf files in the browser" },
];

/** The process exists (also while starting/stopping or when started outside the panel). */
const alive = (s?: ServiceStatus) => !!s && s.state !== "stopped";
const cpu = (s?: ServiceStatus) => (alive(s) ? `${(s!.cpu ?? 0).toFixed(1)}%` : "—");
const memory = (s?: ServiceStatus) => (alive(s) ? `${Math.round((s!.memory ?? 0) / 1048576)} MB` : "—");

function StatCard({ label, value, sub, icon }: { label: string; value: ReactNode; sub: ReactNode; icon: ReactNode }) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between">
        <div className="label-caps">{label}</div>
        <div className="flex size-9 items-center justify-center rounded-lg bg-accent-soft text-accent-text">{icon}</div>
      </div>
      <div className="-mt-1 text-2xl font-semibold">{value}</div>
      <div className="mt-1 text-xs text-muted">{sub}</div>
    </Card>
  );
}

function ProcessCard({ label, s }: { label: string; s?: ServiceStatus }) {
  return (
    <Card className="p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="text-sm font-semibold">{label}</div>
        {s && <StateBadge state={s.state} />}
      </div>
      <div className="grid grid-cols-2 gap-x-6 gap-y-3">
        <Stat label="PID" value={alive(s) ? (s!.pid ?? "—") : "—"} mono />
        <Stat label="Uptime" value={uptime(s?.started_at)} mono />
        <Stat label="CPU" value={cpu(s)} mono />
        <Stat label="Memory" value={memory(s)} mono />
      </div>
    </Card>
  );
}

export function Dashboard() {
  const { data: status, isLoading } = useStatus();
  const world = status?.services.world;
  const auth = status?.services.auth;
  const online = (s?: ServiceStatus) => (isLoading ? "…" : alive(s) ? "Online" : "Offline");
  const sub = (s?: ServiceStatus) => (alive(s) ? `Uptime ${uptime(s!.started_at)}` : "Process stopped");

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Real-time status overview of your AzerothCore server" />
      <div className="space-y-6">
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatCard label="Worldserver" value={online(world)} sub={sub(world)} icon={<Server className="size-4" />} />
          <StatCard label="Authserver" value={online(auth)} sub={sub(auth)} icon={<Activity className="size-4" />} />
          <StatCard label="CPU usage" value={cpu(world)} sub="worldserver process" icon={<HardDrive className="size-4" />} />
          <StatCard label="Memory usage" value={memory(world)} sub="worldserver RSS" icon={<Users className="size-4" />} />
        </div>

        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <ProcessCard label="Worldserver" s={world} />
          <ProcessCard label="Authserver" s={auth} />
          <ProcessCard label="MySQL" s={status?.services.mysql} />
        </div>

        <div>
          <div className="label-caps mb-3">Quick actions</div>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {QUICK_ACTIONS.map((a) => (
              <a
                key={a.to}
                href={`#${a.to}`}
                className="group flex items-start gap-3 rounded-xl border border-line bg-card p-4 transition-colors hover:border-accent/50 hover:bg-card-2"
              >
                <div className="shrink-0 rounded-lg bg-accent-soft p-2 text-accent-text">{a.icon}</div>
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-medium">{a.label}</div>
                  <div className="mt-0.5 text-xs leading-snug text-muted">{a.desc}</div>
                </div>
              </a>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}
