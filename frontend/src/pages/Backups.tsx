import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive, CheckCircle2, ChevronDown, ChevronUp, Clock, Database, FileText, FolderOpen, HardDrive, Play,
  Plus, RefreshCw, RotateCcw, Server, Terminal, Trash2, Wifi, WifiOff, X, XCircle,
} from "lucide-react";
import { del, get, post, put } from "../lib/api";
import { bytes, dateTime } from "../lib/format";
import { useStatus } from "../lib/hooks";
import { Button, Callout, Card, cx, Field, Input, Modal, PageHeader, Spinner, useConfirm, useToast } from "../components/ui";
import { PathInput } from "../components/PathPicker";

interface Destination {
  id: number;
  name: string;
  type: "local";
  path: string;
  enabled: boolean;
  builtin: boolean;
}

interface Include {
  configs: boolean;
  databases: boolean;
  binaries: boolean;
}

interface Job {
  id: number;
  type: "backup" | "restore";
  status: "running" | "completed" | "failed";
  started: number;
  finished: number | null;
  destination_id: number;
  destination_name: string;
  include: Include;
  notes: string;
  file: string | null;
  size: number;
  error: string | null;
  log?: string[];
}

interface ArchiveFile {
  filename: string;
  size: number;
  modified: number;
}

type Tab = "destinations" | "create" | "history";

const INCLUDE_ITEMS: { key: keyof Include; label: string; desc: string; icon: ReactNode }[] = [
  { key: "configs", label: "Config Files", desc: "All .conf files from the server's configs folder", icon: <FileText className="size-4" /> },
  { key: "databases", label: "Databases", desc: "auth, characters, world (mysqldump)", icon: <Database className="size-4" /> },
  { key: "binaries", label: "Server Binaries", desc: "Files in the server folder (worldserver.exe, authserver.exe, DLLs)", icon: <Server className="size-4" /> },
];

// ---- live job log -----------------------------------------------------------------------------

function JobLog({ jobId, title, onClose }: { jobId: number; title: string; onClose: () => void }) {
  const qc = useQueryClient();
  const box = useRef<HTMLDivElement>(null);
  const { data: job } = useQuery({
    queryKey: ["backup-job", jobId],
    queryFn: () => get<Job>(`/api/backups/jobs/${jobId}`),
    refetchInterval: (q) => (q.state.data?.status === "running" ? 1000 : false),
  });
  const done = job && job.status !== "running";

  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [job?.log?.length]);
  useEffect(() => {
    if (done) qc.invalidateQueries({ queryKey: ["backup-jobs"] });
  }, [done, qc]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-3xl rounded-xl border border-line bg-card shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-semibold">
            <Terminal className="size-4 text-accent" /> {title}
          </div>
          <div className="flex items-center gap-3">
            {!done && <Spinner className="size-3.5" />}
            {job?.status === "completed" && (
              <span className="flex items-center gap-1 text-xs font-medium text-ok"><CheckCircle2 className="size-3.5" /> Done</span>
            )}
            {job?.status === "failed" && (
              <span className="flex items-center gap-1 text-xs font-medium text-bad"><XCircle className="size-3.5" /> Error</span>
            )}
            <button onClick={onClose} className="text-muted hover:text-text" aria-label="Close" disabled={!done}>
              <X className="size-4" />
            </button>
          </div>
        </div>
        <div ref={box} className="h-80 overflow-y-auto bg-term p-4 font-mono text-xs leading-5 text-[#c9ccd6]">
          {(job?.log ?? []).map((l, i) => (
            <div key={i} className={cx(l.startsWith("[ERROR]") && "text-[#f27474]", l.startsWith("[WARN]") && "text-[#e9b44c]", l.startsWith("[INFO]") && "text-[#8fb8ff]")}>
              {l}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---- destinations ---------------------------------------------------------------------------------

function DestinationModal({ initial, onClose }: { initial?: Destination; onClose: () => void }) {
  const [name, setName] = useState(initial?.name ?? "");
  const [path, setPath] = useState(initial?.path ?? "");
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const body = { name, path, enabled };
      if (initial) await put(`/api/backups/destinations/${initial.id}`, body);
      else await post("/api/backups/destinations", body);
      qc.invalidateQueries({ queryKey: ["backup-destinations"] });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      title={`${initial ? "Edit" : "Add"} Backup Destination`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!name.trim() || !path.trim()} onClick={save}>
            {initial ? "Save" : "Add Destination"}
          </Button>
        </>
      }
    >
      <Field label="Name">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="My Backup Location" autoFocus />
      </Field>
      <Field label="Type">
        <div className="flex h-9 items-center gap-2 rounded-md border border-accent bg-accent-soft px-3 text-[13px] text-accent-text">
          <HardDrive className="size-4" /> Local folder
        </div>
      </Field>
      <Field label="Folder" hint="A folder on this PC, a USB drive or a mapped network drive. It's created if it doesn't exist.">
        <PathInput value={path} onChange={setPath} placeholder="D:\Backups\AzerothCore" />
      </Field>
      <label className="flex items-center gap-2 text-[13px]">
        <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="accent-[var(--accent)]" />
        Enabled
      </label>
      {error && <Callout tone="bad">{error}</Callout>}
    </Modal>
  );
}

function DestinationsTab({ destinations }: { destinations: Destination[] }) {
  const [modal, setModal] = useState<{ edit?: Destination } | null>(null);
  const [tests, setTests] = useState<Record<number, { ok: boolean; msg: string }>>({});
  const [testing, setTesting] = useState<number | null>(null);
  const qc = useQueryClient();
  const confirm = useConfirm();
  const toast = useToast();

  const test = async (id: number) => {
    setTesting(id);
    try {
      const r = await post<{ success: boolean; message: string }>(`/api/backups/destinations/${id}/test`);
      setTests((t) => ({ ...t, [id]: { ok: r.success, msg: r.message } }));
    } catch (e) {
      setTests((t) => ({ ...t, [id]: { ok: false, msg: (e as Error).message } }));
    } finally {
      setTesting(null);
    }
  };

  const remove = async (d: Destination) => {
    if (!(await confirm({ title: `Delete destination "${d.name}"?`, body: "Backup files already in that folder are not deleted.", confirm: "Delete", danger: true }))) return;
    try {
      await del(`/api/backups/destinations/${d.id}`);
      qc.invalidateQueries({ queryKey: ["backup-destinations"] });
    } catch (e) {
      toast({ tone: "bad", title: "Delete failed", body: (e as Error).message });
    }
  };

  const custom = destinations.filter((d) => !d.builtin);
  return (
    <>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[13px] text-muted">Configure where your backups will be stored.</p>
        <Button variant="primary" size="sm" icon={<Plus className="size-3.5" />} onClick={() => setModal({})}>
          Add Destination
        </Button>
      </div>
      <div className="space-y-3">
        {destinations.map((d) => {
          const t = tests[d.id];
          return (
            <Card key={d.id} className="flex flex-wrap items-center gap-3 p-4">
              <div className={cx("size-2 rounded-full", d.enabled ? "bg-ok" : "bg-faint")} />
              <HardDrive className="size-4 text-muted" />
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium">{d.name}{d.builtin && <span className="ml-2 text-xs text-faint">built-in</span>}</div>
                <div className="truncate font-mono text-xs text-muted">{d.path}</div>
              </div>
              {t && (
                <span className={cx("flex items-center gap-1 text-xs", t.ok ? "text-ok" : "text-bad")}>
                  {t.ok ? <Wifi className="size-3" /> : <WifiOff className="size-3" />} {t.msg}
                </span>
              )}
              <Button size="sm" variant="ghost" loading={testing === d.id} icon={<Wifi className="size-3.5" />} onClick={() => test(d.id)}>
                Test
              </Button>
              {!d.builtin && (
                <>
                  <Button size="sm" variant="ghost" onClick={() => setModal({ edit: d })}>Edit</Button>
                  <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => remove(d)} aria-label="Delete" />
                </>
              )}
            </Card>
          );
        })}
      </div>
      {custom.length === 0 && (
        <p className="mt-4 text-center text-xs text-faint">No extra destinations configured yet. Backups go to the default local storage.</p>
      )}
      {modal && <DestinationModal initial={modal.edit} onClose={() => setModal(null)} />}
    </>
  );
}

// ---- create backup --------------------------------------------------------------------------------

function CreateBackupTab({ destinations, busy }: { destinations: Destination[]; busy: boolean }) {
  const enabled = destinations.filter((d) => d.enabled);
  const [destId, setDestId] = useState(enabled[0]?.id ?? 0);
  const [include, setInclude] = useState<Include>({ configs: true, databases: true, binaries: false });
  const [notes, setNotes] = useState("");
  const [jobId, setJobId] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);
  const toast = useToast();
  // Same list the backup dumps: auth, characters, world (+ playerbots when installed).
  const { data: dbs } = useQuery({ queryKey: ["dbs"], queryFn: () => get<{ key: string }[]>("/api/db") });
  const nothing = !include.configs && !include.databases && !include.binaries;

  const start = async () => {
    setStarting(true);
    try {
      const r = await post<{ job_id: number }>("/api/backups/run", {
        destination_id: destId,
        include_configs: include.configs,
        include_databases: include.databases,
        include_binaries: include.binaries,
        notes,
      });
      setJobId(r.job_id);
      setNotes("");
    } catch (e) {
      toast({ tone: "bad", title: "Backup failed to start", body: (e as Error).message });
    } finally {
      setStarting(false);
    }
  };

  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted">Configure and run a new backup.</p>
      <Card className="p-5">
        <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold"><FolderOpen className="size-4 text-accent" /> Destination</div>
        <div className="space-y-2">
          {enabled.map((d) => (
            <button
              key={d.id}
              onClick={() => setDestId(d.id)}
              className={cx("flex w-full items-center gap-3 rounded-lg border px-4 py-3 text-left transition-colors", destId === d.id ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong")}
            >
              <HardDrive className="size-4 text-muted" />
              <div className="min-w-0">
                <div className="text-[13px] font-medium">{d.name}</div>
                <div className="truncate font-mono text-xs text-muted">{d.path}</div>
              </div>
            </button>
          ))}
        </div>
        {enabled.length === 1 && <p className="mt-2 text-xs text-faint">No enabled destinations – only local storage available.</p>}
      </Card>

      <Card className="p-5">
        <div className="mb-3 flex items-center gap-2 text-[13px] font-semibold"><Archive className="size-4 text-accent" /> What to Include</div>
        <div className="space-y-3">
          {INCLUDE_ITEMS.map((item) => (
            <label key={item.key} className="flex cursor-pointer items-center gap-3">
              <input
                type="checkbox"
                checked={include[item.key]}
                onChange={(e) => setInclude((s) => ({ ...s, [item.key]: e.target.checked }))}
                className="size-4 accent-[var(--accent)]"
              />
              <span className="text-accent-text/70">{item.icon}</span>
              <div>
                <div className="text-[13px] font-medium">{item.label}</div>
                <div className="text-xs text-muted">
                  {item.key === "databases" && dbs ? `${dbs.map((d) => d.key).join(", ")} (mysqldump)` : item.desc}
                </div>
              </div>
            </label>
          ))}
        </div>
        {nothing && (
          <div className="mt-3">
            <Callout tone="warn">Select at least one item to back up.</Callout>
          </div>
        )}
      </Card>

      <Card className="p-5">
        <div className="mb-3 text-[13px] font-semibold">Notes (optional)</div>
        <Input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Before updating the server" maxLength={300} />
      </Card>

      <Button variant="primary" className="h-10 w-full" icon={<Play className="size-4" />} loading={starting || busy} disabled={nothing} onClick={start}>
        {busy ? "Running Backup…" : "Start Backup"}
      </Button>
      {jobId !== null && <JobLog jobId={jobId} title="Backup Progress" onClose={() => setJobId(null)} />}
    </div>
  );
}

// ---- job history -------------------------------------------------------------------------------------

function StatusIcon({ s }: { s: Job["status"] }) {
  if (s === "completed") return <CheckCircle2 className="size-4 text-ok" />;
  if (s === "running") return <RefreshCw className="size-4 animate-spin text-warn" />;
  if (s === "failed") return <XCircle className="size-4 text-bad" />;
  return <Clock className="size-4 text-muted" />;
}

function JobFiles({ job }: { job: Job }) {
  const qc = useQueryClient();
  const confirm = useConfirm();
  const { data: files, isLoading } = useQuery({ queryKey: ["backup-files", job.id], queryFn: () => get<ArchiveFile[]>(`/api/backups/jobs/${job.id}/files`) });

  const remove = async (f: ArchiveFile) => {
    if (!(await confirm({ title: `Delete ${f.filename}?`, body: `The file (${bytes(f.size)}) is permanently deleted from ${job.destination_name}.`, confirm: "Delete", danger: true }))) return;
    await del(`/api/backups/jobs/${job.id}/files/${encodeURIComponent(f.filename)}`);
    qc.invalidateQueries({ queryKey: ["backup-files", job.id] });
  };

  return (
    <div className="border-t border-line bg-card-2/40 px-4 py-3">
      <div className="label-caps mb-2">Files at destination</div>
      {isLoading ? (
        <Spinner className="size-3.5" />
      ) : !files?.length ? (
        <p className="text-xs text-muted">No files found.</p>
      ) : (
        <div className="space-y-1">
          {files.map((f) => (
            <div key={f.filename} className="flex items-center justify-between text-xs">
              <span className={cx("font-mono", f.filename === job.file ? "text-text" : "text-muted")}>{f.filename}</span>
              <div className="flex items-center gap-3 text-muted">
                <span>{bytes(f.size)}</span>
                <span>{dateTime(f.modified)}</span>
                <button onClick={() => remove(f)} className="text-bad hover:brightness-125" aria-label={`Delete ${f.filename}`}>
                  <Trash2 className="size-3" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function RestoreModal({ job, onClose, onStarted }: { job: Job; onClose: () => void; onStarted: (id: number) => void }) {
  const { data: status } = useStatus();
  const [opts, setOpts] = useState<Include>({ configs: job.include.configs, databases: job.include.databases, binaries: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const running = (["world", "auth"] as const).filter((k) => status && status.services[k].state !== "stopped").map((k) => status!.services[k].label);
  const nothing = !opts.configs && !opts.databases && !opts.binaries;

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await post<{ job_id: number }>("/api/backups/restore", {
        job_id: job.id,
        restore_configs: opts.configs,
        restore_databases: opts.databases,
        restore_binaries: opts.binaries,
      });
      onStarted(r.job_id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const items = [
    { key: "configs" as const, label: "Restore Config Files", desc: "Overwrites .conf files (current ones kept as .bak)" },
    { key: "databases" as const, label: "Restore Databases", desc: "Reimports the SQL dumps" },
    { key: "binaries" as const, label: "Restore Server Binaries", desc: "Overwrites files in the server folder" },
  ].filter((i) => job.include[i.key]);

  return (
    <Modal
      open
      title={`Restore from Backup #${job.id}`}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="danger" icon={<RotateCcw className="size-3.5" />} loading={busy} disabled={nothing || running.length > 0} onClick={start}>
            Restore
          </Button>
        </>
      }
    >
      <Callout tone="bad">This will overwrite existing data with the backup from {dateTime(job.started)}.</Callout>
      {running.length > 0 && <Callout tone="warn">Stop {running.join(" and ")} first. MySQL must stay running for a database restore.</Callout>}
      <div className="space-y-3">
        {items.map((i) => (
          <label key={i.key} className="flex cursor-pointer items-center gap-3">
            <input type="checkbox" checked={opts[i.key]} onChange={(e) => setOpts((o) => ({ ...o, [i.key]: e.target.checked }))} className="size-4 accent-[var(--accent)]" />
            <div>
              <div className="text-[13px] font-medium">{i.label}</div>
              <div className="text-xs text-muted">{i.desc}</div>
            </div>
          </label>
        ))}
      </div>
      {error && <Callout tone="bad">{error}</Callout>}
    </Modal>
  );
}

function JobHistoryTab({ jobs, onRefresh }: { jobs: Job[]; onRefresh: () => void }) {
  const [expanded, setExpanded] = useState<number | null>(null);
  const [restoring, setRestoring] = useState<Job | null>(null);
  const [restoreJob, setRestoreJob] = useState<number | null>(null);
  const qc = useQueryClient();
  const confirm = useConfirm();
  const backups = jobs.filter((j) => j.type === "backup");

  const remove = async (j: Job) => {
    if (!(await confirm({ title: `Delete job #${j.id} record?`, body: "Only the history entry is removed; the backup file stays at its destination.", confirm: "Delete", danger: true }))) return;
    await del(`/api/backups/jobs/${j.id}`);
    qc.invalidateQueries({ queryKey: ["backup-jobs"] });
  };

  return (
    <>
      <div className="mb-4 flex items-center justify-between">
        <p className="text-[13px] text-muted">History of all backup jobs.</p>
        <Button size="sm" variant="ghost" icon={<RefreshCw className="size-3.5" />} onClick={onRefresh}>Refresh</Button>
      </div>
      {backups.length === 0 ? (
        <div className="flex flex-col items-center gap-2 py-14 text-muted">
          <Clock className="size-8 opacity-40" />
          <p className="text-[13px]">No backup jobs yet.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {backups.map((j) => (
            <Card key={j.id} className="overflow-hidden">
              <div className="flex items-center gap-3 p-4">
                <StatusIcon s={j.status} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={cx("text-[13px] font-medium", j.status === "completed" ? "text-ok" : j.status === "failed" ? "text-bad" : "text-warn")}>
                      {j.status[0].toUpperCase() + j.status.slice(1)}
                    </span>
                    <span className="text-xs text-muted">#{j.id}</span>
                    {j.notes && <span className="max-w-[300px] truncate text-xs text-muted">{j.notes}</span>}
                  </div>
                  <div className="mt-0.5 flex flex-wrap items-center gap-3 text-xs text-muted">
                    <span>{dateTime(j.started)}</span>
                    {j.size > 0 && <span>{bytes(j.size)}</span>}
                    <span>{j.destination_name}</span>
                  </div>
                  <div className="mt-1 flex items-center gap-3 text-xs text-muted">
                    {j.include.configs && <span className="flex items-center gap-1"><FileText className="size-2.5" /> Configs</span>}
                    {j.include.databases && <span className="flex items-center gap-1"><Database className="size-2.5" /> Databases</span>}
                    {j.include.binaries && <span className="flex items-center gap-1"><Server className="size-2.5" /> Binaries</span>}
                  </div>
                  {j.error && <p className="mt-1 truncate text-xs text-bad">{j.error}</p>}
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {j.status === "completed" && (
                    <Button size="sm" variant="ghost" icon={<RotateCcw className="size-3.5" />} onClick={() => setRestoring(j)}>
                      Restore
                    </Button>
                  )}
                  <button onClick={() => setExpanded(expanded === j.id ? null : j.id)} className="p-1 text-muted hover:text-text" aria-label="Show files">
                    {expanded === j.id ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
                  </button>
                  <Button size="sm" variant="ghost" className="!text-bad" icon={<Trash2 className="size-3.5" />} onClick={() => remove(j)} aria-label="Delete record" />
                </div>
              </div>
              {expanded === j.id && <JobFiles job={j} />}
            </Card>
          ))}
        </div>
      )}
      {restoring && (
        <RestoreModal
          job={restoring}
          onClose={() => setRestoring(null)}
          onStarted={(id) => {
            setRestoring(null);
            setRestoreJob(id);
          }}
        />
      )}
      {restoreJob !== null && <JobLog jobId={restoreJob} title="Restore Progress" onClose={() => setRestoreJob(null)} />}
    </>
  );
}

// ---- page -----------------------------------------------------------------------------------------------

export function Backups() {
  const [tab, setTab] = useState<Tab>("destinations");
  const { data: destinations, error: destError } = useQuery({ queryKey: ["backup-destinations"], queryFn: () => get<Destination[]>("/api/backups/destinations") });
  const jobs = useQuery({
    queryKey: ["backup-jobs"],
    queryFn: () => get<{ jobs: Job[]; busy: boolean }>("/api/backups/jobs"),
    refetchInterval: (q) => (q.state.data?.busy ? 2000 : false),
  });

  const tabs: { key: Tab; label: string }[] = [
    { key: "destinations", label: "Destinations" },
    { key: "create", label: "Create Backup" },
    { key: "history", label: "Job History" },
  ];

  return (
    <>
      <PageHeader title="Backup & Restore" subtitle="Back up configs, databases, and server files to local folders." />
      <div className="mb-5 flex gap-1 border-b border-line">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={cx("-mb-px border-b-2 px-4 py-2 text-[13px] font-medium transition-colors", tab === t.key ? "border-accent text-accent-text" : "border-transparent text-muted hover:text-text")}
          >
            {t.label}
          </button>
        ))}
      </div>
      {destError || jobs.error ? (
        <Callout tone="bad">Couldn't load backups: {((destError ?? jobs.error) as Error).message}</Callout>
      ) : !destinations || !jobs.data ? (
        <Spinner />
      ) : tab === "destinations" ? (
        <DestinationsTab destinations={destinations} />
      ) : tab === "create" ? (
        <CreateBackupTab destinations={destinations} busy={jobs.data.busy} />
      ) : (
        <JobHistoryTab jobs={jobs.data.jobs} onRefresh={() => jobs.refetch()} />
      )}
    </>
  );
}
