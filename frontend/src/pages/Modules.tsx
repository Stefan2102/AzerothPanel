import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2, ChevronLeft, ChevronRight, Download, ExternalLink, GitBranch, GitFork, Hammer, Link2Off, Loader2, RefreshCw, Search, Star, Trash2, X,
} from "lucide-react";
import { ApiError, del, get, post, type Status } from "../lib/api";
import { date, dateTime } from "../lib/format";
import { useStatus } from "../lib/hooks";
import { type JobBase } from "../components/JobOutput";
import { Badge, Button, buttonClass, Callout, Card, CardHeader, cx, Input, PageHeader, Select, Spinner, useConfirm, useToast } from "../components/ui";

interface CatalogueItem {
  id: number;
  name: string;
  full_name: string;
  description: string;
  stars: number;
  forks: number;
  created: string;
  pushed: string;
  url: string;
  owner: string;
  avatar: string;
  branch: string;
}

interface Catalogue {
  fetched: number;
  stale?: string;
  categories: Record<Category, CatalogueItem[]>;
}

interface InstalledModule {
  name: string;
  link: string | null;
  broken: boolean;
  git: boolean;
  branch?: string | null;
  commit?: string | null;
  date?: string | null;
  remote?: string | null;
  dirty?: boolean | null;
  repo: string | null;
}

interface Installed {
  source: string;
  modules: InstalledModule[];
  git: boolean;
  busy: boolean;
  rebuild_needed: boolean;
}

interface ModuleJob extends JobBase {
  type: "install" | "update" | "update-all" | "remove";
  name: string | null;
  changed?: boolean;
  failed?: string[];
}

type Category = "modules" | "tools" | "lua" | "sql";
type Sort = "stars" | "pushed" | "created";

const CATEGORIES: { key: Category; label: string }[] = [
  { key: "modules", label: "All Modules" },
  { key: "tools", label: "Tools" },
  { key: "lua", label: "Lua scripts" },
  { key: "sql", label: "SQL" },
];
const SORTS: { key: Sort; label: string }[] = [
  { key: "stars", label: "Most stars" },
  { key: "pushed", label: "Recently updated" },
  { key: "created", label: "Recently added" },
];
const PAGE = 30;
const DONE_LABEL: Record<string, string> = { install: "Installed", update: "Updated", "update-all": "Updated all modules", remove: "Removed" };
const FAIL_LABEL: Record<string, string> = { install: "Install of", update: "Update of", "update-all": "Update of all modules", remove: "Removal of" };

// ---- catalogue --------------------------------------------------------------------------------------------

function RepoCard({ item, installed, canInstall, busy, onInstall }: {
  item: CatalogueItem; installed: boolean; canInstall: boolean; busy: boolean; onInstall: () => void;
}) {
  return (
    <Card className="flex flex-col p-4">
      <div className="flex items-start gap-3">
        <img src={item.avatar} alt="" loading="lazy" className="size-10 shrink-0 rounded-full bg-card-2" />
        <div className="min-w-0">
          <a href={item.url} target="_blank" rel="noreferrer noopener" className="flex items-center gap-1.5 text-[13px] font-semibold hover:text-accent-text">
            <span className="truncate">{item.name}</span> <ExternalLink className="size-3 shrink-0 text-muted" />
            {installed && <Badge tone="ok">installed</Badge>}
          </a>
          <div className="truncate text-xs text-muted">{item.full_name}</div>
        </div>
      </div>
      <p className="mt-3 line-clamp-2 min-h-[2.5rem] text-[13px] text-muted">{item.description || "No description."}</p>
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted">
        <span className="flex items-center gap-1"><Star className="size-3.5" /> {item.stars.toLocaleString()}</span>
        <span className="flex items-center gap-1"><GitFork className="size-3.5" /> {item.forks.toLocaleString()}</span>
        <span>Updated {date(item.pushed)}</span>
      </div>
      <div className="mt-auto pt-4">
        {canInstall ? (
          <Button variant={installed ? "default" : "primary"} className="w-full" icon={installed ? <CheckCircle2 className="size-4" /> : <Download className="size-4" />}
            disabled={installed || busy} onClick={onInstall}>
            {installed ? "Already installed" : "Install"}
          </Button>
        ) : (
          <a href={item.url} target="_blank" rel="noreferrer noopener" className={buttonClass("default", "md", "w-full")}>
            <ExternalLink className="size-4" /> Open on GitHub
          </a>
        )}
      </div>
    </Card>
  );
}

function CatalogueTab({ installed, busy, onStarted }: { installed: Installed | undefined; busy: boolean; onStarted: (id: number) => void }) {
  const [category, setCategory] = useState<Category>("modules");
  const [sort, setSort] = useState<Sort>("stars");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading, error } = useQuery({ queryKey: ["modules-catalogue"], queryFn: () => get<Catalogue>("/api/modules/catalogue"), staleTime: 10 * 60_000 });

  const installedRepos = useMemo(() => new Set((installed?.modules ?? []).map((m) => m.repo).filter(Boolean)), [installed]);
  const installedNames = useMemo(() => new Set((installed?.modules ?? []).map((m) => m.name.toLowerCase())), [installed]);

  const items = useMemo(() => {
    const list = data?.categories[category] ?? [];
    const q = query.trim().toLowerCase();
    const filtered = q ? list.filter((i) => i.name.toLowerCase().includes(q) || i.description.toLowerCase().includes(q)) : list;
    const time = (s: string) => new Date(s).getTime() || 0;
    return [...filtered].sort((a, b) => (sort === "stars" ? b.stars - a.stars : time(b[sort]) - time(a[sort])));
  }, [data, category, query, sort]);

  const pages = Math.max(1, Math.ceil(items.length / PAGE));
  const current = Math.min(page, pages - 1);
  const shown = items.slice(current * PAGE, current * PAGE + PAGE);

  const go = (n: number) => {
    setPage(n);
    window.scrollTo?.({ top: 0 });
    document.querySelector("main")?.scrollTo({ top: 0, behavior: "smooth" });
  };
  const pager = pages > 1 && (
    <div className="flex items-center gap-2">
      <Button size="sm" variant="ghost" icon={<ChevronLeft className="size-3.5" />} disabled={current === 0} onClick={() => go(current - 1)}>Prev</Button>
      <span>Page {current + 1} / {pages}</span>
      <Button size="sm" variant="ghost" disabled={current >= pages - 1} onClick={() => go(current + 1)}>Next <ChevronRight className="size-3.5" /></Button>
    </div>
  );

  const refresh = async () => {
    setRefreshing(true);
    try {
      qc.setQueryData(["modules-catalogue"], await get<Catalogue>("/api/modules/catalogue?refresh=true"));
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't refresh the catalogue", body: (e as Error).message });
    } finally {
      setRefreshing(false);
    }
  };

  const install = async (item: CatalogueItem) => {
    try {
      onStarted((await post<{ job_id: number }>("/api/modules/install", { full_name: item.full_name })).job_id);
    } catch (e) {
      toast({ tone: "bad", title: `Couldn't install ${item.name}`, body: (e as Error).message });
    }
  };

  return (
    <div className="space-y-4">
      <Card className="space-y-4 p-4">
        <div className="flex border-b border-line">
          {CATEGORIES.map((c) => (
            <button key={c.key} onClick={() => { setCategory(c.key); setPage(0); }}
              className={cx("-mb-px flex-1 border-b-2 px-3 py-2 text-[13px] transition-colors",
                category === c.key ? "border-accent font-medium text-accent-text" : "border-transparent text-muted hover:text-text")}>
              {c.label}
              {data && <span className="ml-1.5 text-xs text-faint">{data.categories[c.key]?.length ?? 0}</span>}
            </button>
          ))}
        </div>
        <div className="grid items-center gap-3 md:grid-cols-[1fr_14rem_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute top-2.5 left-3 size-4 text-faint" />
            <Input className="pl-9" placeholder="Search an item in the catalogue" value={query} onChange={(e) => { setQuery(e.target.value); setPage(0); }} />
          </div>
          <Select value={sort} onChange={(e) => setSort(e.target.value as Sort)}>
            {SORTS.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </Select>
          <Button variant="ghost" icon={<RefreshCw className={cx("size-4", refreshing && "animate-spin")} />} onClick={refresh} title="Load the newest catalogue">
            Refresh
          </Button>
        </div>
        {category !== "modules" && (
          <p className="text-xs text-faint">Tools, Lua and SQL scripts are not modules; open them on GitHub to see how to use them.</p>
        )}
      </Card>

      {isLoading && <Spinner />}
      {error && <Callout tone="bad">{(error as Error).message}</Callout>}
      {data?.stale && <Callout tone="warn">Showing the last saved catalogue; the newest one couldn't be loaded ({data.stale}).</Callout>}
      {data && (
        <>
          <div className="flex items-center justify-between text-xs text-muted">
            <span>
              {items.length ? `Showing ${current * PAGE + 1}–${current * PAGE + shown.length} of ${items.length}` : "Nothing matches."}
              <span className="ml-2 text-faint">Catalogue from azerothcore.org, loaded {dateTime(data.fetched)}</span>
            </span>
            {pager}
          </div>
          <div className="grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
            {shown.map((item) => (
              <RepoCard
                key={item.id}
                item={item}
                installed={installedRepos.has(item.full_name.toLowerCase()) || (category === "modules" && installedNames.has(item.name.toLowerCase()))}
                canInstall={category === "modules"}
                busy={busy || !installed}
                onInstall={() => install(item)}
              />
            ))}
          </div>
          {pages > 1 && <div className="flex justify-end text-xs text-muted">{pager}</div>}
        </>
      )}
    </div>
  );
}

// ---- installed ----------------------------------------------------------------------------------------------

function InstalledTab({ installed, busy, onStarted }: { installed: Installed; busy: boolean; onStarted: (id: number) => void }) {
  const confirm = useConfirm();
  const toast = useToast();
  const [url, setUrl] = useState("");

  const run = async (what: string, action: () => Promise<{ job_id: number }>) => {
    try {
      onStarted((await action()).job_id);
    } catch (e) {
      toast({ tone: "bad", title: `${what} didn't start`, body: (e as Error).message });
    }
  };

  const remove = async (m: InstalledModule) => {
    const ok = await confirm({
      title: `Remove ${m.name}?`,
      body: m.link
        ? `modules\\${m.name} is a link to ${m.link}. Only the link is removed; that folder is not touched.`
        : `The folder modules\\${m.name} is deleted${m.dirty ? ", INCLUDING YOUR LOCAL CHANGES in it" : ""}. Rebuild and deploy afterwards to take it out of the server. Its settings stay in the server's configs folder, unused, in case you install it again.`,
      confirm: "Remove",
      danger: true,
    });
    if (ok) await run(`Removing ${m.name}`, () => del<{ job_id: number }>(`/api/modules/${encodeURIComponent(m.name)}`));
  };

  return (
    <Card>
      <CardHeader
        title={`Installed modules (${installed.modules.length})`}
        subtitle={<span className="font-mono">{installed.source}\modules</span>}
        right={
          <Button size="sm" icon={<RefreshCw className="size-3.5" />} disabled={busy || !installed.git || !installed.modules.some((m) => m.git && !m.broken)}
            onClick={() => run("Update all", () => post<{ job_id: number }>("/api/modules/update-all"))}>
            Update All Modules
          </Button>
        }
      />
      {installed.modules.length === 0 && <p className="px-4 py-8 text-center text-[13px] text-muted">No modules installed. Install one from the catalogue.</p>}
      <div className="divide-y divide-line">
        {installed.modules.map((m) => (
          <div key={m.name} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3">
            {m.broken ? <Link2Off className="size-4 shrink-0 text-bad" /> : <CheckCircle2 className="size-4 shrink-0 text-ok" />}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] font-medium">{m.name}</span>
                {m.git ? <Badge tone="muted">git</Badge> : <Badge tone="warn">no git</Badge>}
                {m.dirty && <Badge tone="warn">local changes</Badge>}
                {m.link && !m.broken && <Badge tone="muted">link</Badge>}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-3 text-xs text-muted">
                {m.remote && <a href={m.remote.replace(/\.git$/, "")} target="_blank" rel="noreferrer noopener" className="hover:text-accent-text">{m.remote}</a>}
                {m.git && <span className="flex items-center gap-1 font-mono"><GitBranch className="size-3" />{m.branch}@{m.commit}</span>}
                {m.broken && <span className="text-bad">links to {m.link}, which no longer exists</span>}
              </div>
            </div>
            {m.git && !m.broken && (
              <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} disabled={busy}
                onClick={() => run(`Updating ${m.name}`, () => post<{ job_id: number }>(`/api/modules/${encodeURIComponent(m.name)}/update`))}>
                Update
              </Button>
            )}
            <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} disabled={busy} onClick={() => remove(m)}>Remove</Button>
          </div>
        ))}
      </div>
      <div className="border-t border-line px-4 py-3">
        <div className="mb-1.5 text-xs font-medium text-muted">Install from Git URL (modules that are not in the catalogue)</div>
        <div className="flex gap-2">
          <Input className="font-mono" placeholder="https://github.com/owner/mod-name.git" value={url} onChange={(e) => setUrl(e.target.value)} />
          <Button icon={<Download className="size-4" />} disabled={busy || !url.trim().startsWith("https://")}
            onClick={() => run("Install", async () => { const r = await post<{ job_id: number }>("/api/modules/install-url", { url: url.trim() }); setUrl(""); return r; })}>
            Install
          </Button>
        </div>
      </div>
      <div className="border-t border-line px-4 py-3 text-xs text-faint">
        After installing, updating or removing modules, rebuild the server on the Compilation page. Module SQL is applied by
        AzerothCore itself when worldserver starts; deploy creates the module .conf files.
      </div>
    </Card>
  );
}

// ---- page ------------------------------------------------------------------------------------------------------

const RUNNING_LABEL: Record<string, string> = { install: "Installing", update: "Updating", "update-all": "Updating all modules", remove: "Removing" };

/** The module job that is running: what it does, git's progress, and Cancel. */
function RunningJob({ job }: { job: NonNullable<Status["modules"]> }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [cancelling, setCancelling] = useState(false);
  const cancel = async () => {
    setCancelling(true);
    try {
      await post(`/api/modules/jobs/${job.id}/cancel`);
      qc.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't cancel", body: (e as Error).message });
      setCancelling(false);
    }
  };
  // update-all counts modules; install and update show git's own meter (in detail) once it starts.
  const showBar = job.type === "update-all" || !!job.detail;
  return (
    <Card className="mb-4 px-4 py-3">
      <div className="flex items-center gap-3">
        <Loader2 className="size-4 shrink-0 animate-spin text-accent" />
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium">{RUNNING_LABEL[job.type] ?? job.type}{job.name ? ` ${job.name}` : ""}</div>
          <div className="truncate text-xs text-muted">{job.detail ?? (job.type === "remove" ? "Deleting the folder…" : "Starting…")}</div>
        </div>
        <Button size="sm" variant="danger" icon={<X className="size-3.5" />} loading={cancelling} onClick={cancel}>Cancel</Button>
      </div>
      {showBar && (
        <div className="mt-2.5 h-1.5 overflow-hidden rounded-full bg-card-2">
          <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${job.progress}%` }} />
        </div>
      )}
    </Card>
  );
}

export function Modules() {
  const [tab, setTab] = useState<"catalogue" | "installed">("catalogue");
  const { data: status } = useStatus();
  const qc = useQueryClient();
  const toast = useToast();
  const { data: installed, error } = useQuery({ queryKey: ["modules-installed"], queryFn: () => get<Installed>("/api/modules/installed") });
  const runningId = status?.modules?.id ?? null;
  const busy = !!runningId || !!status?.build;

  // No output box: follow the started job quietly, then report it as a toast and refresh the lists.
  // Keeps following on another page (the toast still comes); gives up when signed out, when the job is gone,
  // or when the panel stays unreachable for 5 minutes.
  const started = async (id: number) => {
    qc.invalidateQueries({ queryKey: ["status"] });
    let job: ModuleJob | null = null;
    let unreachableSince: number | null = null;
    for (;;) {
      try {
        job = await get<ModuleJob>(`/api/modules/jobs/${id}?after=999999999`);
        unreachableSince = null;
        if (job.status !== "running") break;
      } catch (e) {
        if (e instanceof ApiError) return;                       // signed out or job gone: nothing to report
        unreachableSince ??= Date.now();                         // panel restarting: try again for a while
        if (Date.now() - unreachableSince > 5 * 60_000) return;
      }
      await new Promise((r) => setTimeout(r, 1000));
    }
    qc.invalidateQueries({ queryKey: ["modules-installed"] });
    qc.invalidateQueries({ queryKey: ["status"] });
    const what = `${DONE_LABEL[job.type]}${job.name ? ` ${job.name}` : ""}`;
    if (job.status === "cancelled") {
      toast({ tone: "ok", title: `${FAIL_LABEL[job.type]}${job.name ? ` ${job.name}` : ""} cancelled`, body: job.type === "install" ? "Nothing was installed." : undefined });
    } else if (job.status !== "completed") {
      toast({ tone: "bad", title: `${FAIL_LABEL[job.type]}${job.name ? ` ${job.name}` : ""} failed`, body: job.error ?? undefined });
    } else if (job.failed?.length) {
      toast({ tone: "bad", title: "Some modules were not updated", body: `${job.failed.join(", ")}: local changes or a diverged branch.` });
    } else {
      toast({ tone: "ok", title: job.changed ? what : `${what}: nothing changed`, body: job.changed ? "Rebuild the server on the Compilation page to use it." : undefined });
    }
  };

  return (
    <>
      <PageHeader title="Modules" subtitle="Browse and install AzerothCore modules from the catalogue" />
      {error && <div className="mb-4"><Callout tone="bad">{(error as Error).message}</Callout></div>}
      {installed?.rebuild_needed && (
        <div className="mb-4">
          <Callout tone="accent">
            <span className="flex flex-wrap items-center gap-2">
              Modules changed since the last build. <a href="#/compilation" className="inline-flex items-center gap-1 font-medium underline"><Hammer className="size-3.5" /> Rebuild on the Compilation page</a> to use them.
            </span>
          </Callout>
        </div>
      )}
      {status?.build && <div className="mb-4"><Callout tone="warn">A build or source update is running; modules can be changed after it.</Callout></div>}
      {status?.modules && <RunningJob job={status.modules} />}
      <div className="mb-4 flex gap-1 border-b border-line">
        {(["catalogue", "installed"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={cx("-mb-px border-b-2 px-4 py-2 text-[13px] transition-colors",
              tab === t ? "border-accent font-medium text-accent-text" : "border-transparent text-muted hover:text-text")}>
            {t === "catalogue" ? "Browse Catalogue" : `Installed (${installed?.modules.length ?? "…"})`}
          </button>
        ))}
      </div>
      {tab === "catalogue" ? (
        <CatalogueTab installed={installed} busy={busy} onStarted={started} />
      ) : installed ? (
        <InstalledTab installed={installed} busy={busy} onStarted={started} />
      ) : (
        !error && <Spinner />
      )}
    </>
  );
}
