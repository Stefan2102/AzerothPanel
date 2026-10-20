import { useEffect, useRef, type ReactNode } from "react";
import {
  AppWindow, Archive, Database, Download, FileCog, FileText, Hammer, HardDrive, LayoutDashboard, Package, Loader2, LogOut, Power, Server, Settings, Shield, Terminal, Users,
} from "lucide-react";
import { get, post, SERVICE_ORDER } from "../lib/api";
import { useLaunchShortcut, useShortcuts, useStatus } from "../lib/hooks";
import { cx, useConfirm, useToast } from "./ui";

const NAV: { section: string; items: { to: string; label: string; icon: ReactNode }[] }[] = [
  {
    section: "Monitor",
    items: [
      { to: "/", label: "Dashboard", icon: <LayoutDashboard className="size-4" /> },
      { to: "/console", label: "Console", icon: <Terminal className="size-4" /> },
      { to: "/logs", label: "Logs", icon: <FileText className="size-4" /> },
    ],
  },
  {
    section: "Manage",
    items: [
      { to: "/server", label: "Server Control", icon: <Server className="size-4" /> },
      { to: "/players", label: "Players", icon: <Users className="size-4" /> },
      { to: "/database", label: "Database", icon: <Database className="size-4" /> },
      { to: "/backups", label: "Backup & Restore", icon: <Archive className="size-4" /> },
    ],
  },
  {
    section: "Build & Deploy",
    items: [
      { to: "/setup", label: "Setup", icon: <Download className="size-4" /> },
      { to: "/compilation", label: "Compilation", icon: <Hammer className="size-4" /> },
      { to: "/data-extraction", label: "Data Extraction", icon: <HardDrive className="size-4" /> },
      { to: "/modules", label: "Modules", icon: <Package className="size-4" /> },
    ],
  },
  {
    section: "Configure",
    items: [
      { to: "/configs", label: "Config Files", icon: <FileCog className="size-4" /> },
      { to: "/settings", label: "Settings", icon: <Settings className="size-4" /> },
    ],
  },
];

const SHORT: Record<string, string> = { world: "World", auth: "Auth", mysql: "MySQL" };
/** Long background jobs shown in the header and announced when they end. */
const BACKGROUND = {
  build: {
    base: "/api/build",
    page: "#/compilation",
    running: { build: "Building", deploy: "Deploying", pull: "Updating source" } as Record<string, string>,
    name: { build: "Build", deploy: "Deploy", pull: "Source update" } as Record<string, string>,
    step: { pull: "pulling source", configure: "configuring", build: "compiling", deploy: "deploying" } as Record<string, string>,
    percentStep: "build",
  },
  data: {
    base: "/api/client-data",
    page: "#/data-extraction",
    running: { download: "Downloading client data", extract: "Extracting client data" } as Record<string, string>,
    name: { download: "Client data download", extract: "Client data extraction" } as Record<string, string>,
    step: { download: "downloading", extract: "unpacking", install: "installing", dbc_maps: "DBC & maps", vmaps: "vmaps", mmaps: "mmaps" } as Record<string, string>,
    percentStep: "*",
  },
  modules: {
    base: "/api/modules",
    page: "#/modules",
    running: { install: "Installing module", update: "Updating module", "update-all": "Updating modules", remove: "Removing module" } as Record<string, string>,
    name: { install: "Module install", update: "Module update", "update-all": "Module update", remove: "Module removal" } as Record<string, string>,
    step: { install: "downloading", update: "pulling", "update-all": "updating" } as Record<string, string>,
    percentStep: "*",
  },
  source: {
    base: "/api/source",
    page: "#/setup",
    running: { clone: "Cloning source" } as Record<string, string>,
    name: { clone: "Source clone" } as Record<string, string>,
    step: { source: "downloading", modules: "modules" } as Record<string, string>,
    percentStep: "*",
  },
  sqlimport: {
    base: "/api/sql-import",
    page: "#/database",
    running: { import: "Importing SQL" } as Record<string, string>,
    name: { import: "SQL import" } as Record<string, string>,
    step: { backup: "backing up", import: "importing" } as Record<string, string>,
    percentStep: "*",
  },
} as const;
type BackgroundKind = keyof typeof BACKGROUND;

function useFinishedToast(kind: BackgroundKind, id: number | null) {
  const toast = useToast();
  const last = useRef<number | null>(null);
  useEffect(() => {
    const finished = last.current;
    last.current = id;
    if (finished === null || id !== null) return;
    const meta = BACKGROUND[kind];
    get<{ type: string; status: string; error: string | null; deployed?: boolean }>(`${meta.base}/jobs/${finished}`).then((j) => {
      const what = meta.name[j.type] ?? j.type;
      if (j.status === "completed") toast({ tone: "ok", title: `${what} #${finished} finished${j.type === "build" && j.deployed ? " and deployed" : ""}` });
      else toast({ tone: "bad", title: `${what} #${finished} ${j.status}`, body: j.error ?? undefined });
    }, () => {});
  }, [kind, id, toast]);
}

export function Layout({ route, username, children, onLogout }: { route: string; username: string; children: ReactNode; onLogout: () => void }) {
  const { data: status } = useStatus();
  const { data: shortcuts } = useShortcuts();
  const launch = useLaunchShortcut();
  const toast = useToast();
  const confirm = useConfirm();
  const lastJob = useRef<number | null>(null);
  // The page area is one scroll box shared by all pages: start each page at its top.
  const main = useRef<HTMLElement>(null);
  useEffect(() => {
    main.current?.scrollTo({ top: 0 });     // a block body: newer browsers return a Promise from scrollTo
  }, [route]);

  // Announce finished lifecycle jobs (start/stop/restart) as toasts.
  useEffect(() => {
    const job = status?.last_job;
    if (!job) return;
    if (lastJob.current !== null && job.finished !== lastJob.current) {
      toast(job.ok ? { tone: "ok", title: `${job.name}: done` } : { tone: "bad", title: `${job.name} failed`, body: job.error ?? undefined });
    }
    lastJob.current = job.finished;
  }, [status?.last_job, toast]);

  // Announce finished builds and client-data jobs (they take a while; you may be on another page).
  useFinishedToast("build", status?.build?.id ?? null);
  useFinishedToast("data", status?.data?.id ?? null);
  useFinishedToast("source", status?.source?.id ?? null);
  useFinishedToast("sqlimport", status?.sqlimport?.id ?? null);

  const shutdownPanel = async () => {
    const ok = await confirm({
      title: "Shut down the panel?",
      body: "Every server the panel started is stopped safely first (worldserver saves players, then authserver, then MySQL). Servers started outside the panel keep running. Start the panel again with start.bat.",
      confirm: "Shut down",
      danger: true,
    });
    if (!ok) return;
    await post("/api/panel/shutdown");
    toast({ tone: "accent", title: "Panel is shutting down", body: "Servers are being stopped safely. You can close this tab." });
  };

  const logout = async () => {
    try {
      await post("/api/auth/logout");
    } finally {
      onLogout();
    }
  };

  return (
    <div className="flex h-full">
      <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-sidebar">
        <div className="flex h-14 items-center gap-2.5 border-b border-line px-5">
          <Shield className="size-5 text-accent" />
          <span className="text-[15px] font-semibold">AzerothPanel</span>
        </div>
        <nav className="flex-1 overflow-y-auto px-3 py-2">
          {NAV.map((group) => (
            <div key={group.section} className="mt-3">
              <div className="label-caps px-2 pb-1.5 !text-[10.5px] !text-faint">{group.section}</div>
              {group.items.map((item) => {
                const active = item.to === "/" ? route === "/" : route.startsWith(item.to);
                return (
                  <a
                    key={item.to}
                    href={`#${item.to}`}
                    className={cx(
                      "mb-0.5 flex h-9 items-center gap-2.5 rounded-lg px-2.5 text-[13px] transition-colors",
                      active ? "bg-accent-soft font-medium text-accent-text" : "text-muted hover:bg-card-2 hover:text-text",
                    )}
                  >
                    {item.icon}
                    {item.label}
                  </a>
                );
              })}
            </div>
          ))}
          <div className="mt-3">
            <div className="flex items-center justify-between px-2 pb-1.5">
              <span className="label-caps !text-[10.5px] !text-faint">Shortcuts</span>
              <a href="#/shortcuts" className={cx("text-[11px] hover:text-text", route === "/shortcuts" ? "text-accent-text" : "text-faint")}>
                Manage
              </a>
            </div>
            {shortcuts?.items.map((s) => (
              <button
                key={s.id}
                onClick={() => launch(s)}
                title={`Start ${s.path}${s.args ? ` ${s.args}` : ""}`}
                className="mb-0.5 flex h-9 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-[13px] text-muted transition-colors hover:bg-card-2 hover:text-text"
              >
                <AppWindow className="size-4 shrink-0" />
                <span className="truncate">{s.name}</span>
              </button>
            ))}
            {shortcuts && shortcuts.items.length === 0 && (
              <a href="#/shortcuts" className="block px-2.5 py-1.5 text-xs text-faint hover:text-text">Add a shortcut</a>
            )}
          </div>
        </nav>
        <div className="border-t border-line px-3 py-3">
          <div className="px-2 pb-2 text-xs text-faint">
            Signed in as <span className="text-text">{username}</span>
          </div>
          <button onClick={logout} className="flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-muted hover:bg-card-2 hover:text-text">
            <LogOut className="size-4" /> Sign out
          </button>
          <button onClick={shutdownPanel} className="flex h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-[13px] text-muted hover:bg-bad-soft hover:text-bad">
            <Power className="size-4" /> Shut down panel
          </button>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-end gap-4 border-b border-line px-6">
          {!status?.job && (["build", "data", "modules", "source", "sqlimport"] as const).some((k) => status?.[k]) && (
            <div className="mr-auto flex min-w-0 items-center gap-5">
              {(["build", "data", "modules", "source", "sqlimport"] as const).map((kind) => {
                const job = status?.[kind];
                if (!job) return null;
                const meta = BACKGROUND[kind];
                const percent = meta.percentStep === "*" || job.step === meta.percentStep;
                return (
                  <a key={kind} href={meta.page} className="flex min-w-0 items-center gap-2 text-xs text-muted hover:text-text">
                    <Loader2 className="size-3.5 shrink-0 animate-spin text-accent" />
                    <span className="truncate">
                      <span className="text-text">{meta.running[job.type] ?? job.type}</span>
                      {job.step && meta.step[job.step] && <> — {meta.step[job.step]}{percent && ` ${job.progress}%`}</>}
                      {job.step === meta.percentStep && !meta.step[job.step] && ` ${job.progress}%`}
                    </span>
                  </a>
                );
              })}
            </div>
          )}
          {status?.job && (
            <div className="mr-auto flex min-w-0 items-center gap-2 text-xs text-muted">
              <Loader2 className="size-3.5 shrink-0 animate-spin text-accent" />
              <span className="truncate">
                <span className="text-text">{status.job.name}</span>
                {status.job.step && <> — {status.job.step}</>}
              </span>
            </div>
          )}
          <div className="flex items-center gap-4 text-xs text-muted">
            {SERVICE_ORDER.slice().reverse().map((key) => {
              const s = status?.services[key];
              const up = s && (s.state === "running" || s.state === "external");
              const busy = s && (s.state === "starting" || s.state === "stopping");
              return (
                <span key={key} className="flex items-center gap-1.5" title={s?.state}>
                  <span className={cx("size-2 rounded-full", up ? "bg-ok" : busy ? "pulse bg-warn" : "bg-bad", !s?.managed && key === "mysql" && !up && "bg-faint")} />
                  {SHORT[key]}
                </span>
              );
            })}
          </div>
        </header>
        <main ref={main} className="min-h-0 flex-1 overflow-y-auto px-6 py-6">{children}</main>
      </div>
    </div>
  );
}
