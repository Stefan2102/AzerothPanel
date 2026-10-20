import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Info, RotateCcw, Save, SlidersHorizontal } from "lucide-react";
import { get, put } from "../lib/api";
import { Badge, Button, Card, cx, Input, PasswordInput, Spinner, useToast } from "./ui";
import { PathInput } from "./PathPicker";

type State = "applied" | "differs";
interface FileState {
  file: string;
  current: string;
  state: State;
  key?: string;
}
interface ValuesStatus {
  configs_found: boolean;
  paths: Record<"DataDir" | "LogsDir" | "MySQLExecutable", { value: string; default: string; files: FileState[] }>;
  db: { host: string; port: number | null; user: string; password_set: boolean; source: "saved" | "configs" | null; files: FileState[] };
}
type PathKey = keyof ValuesStatus["paths"];

const PATHS: { key: PathKey; label: string; hint: string }[] = [
  { key: "DataDir", label: "DataDir", hint: "Client data (dbc, maps, vmaps, mmaps). Relative to the server folder." },
  { key: "LogsDir", label: "LogsDir", hint: "Server logs. Relative to the server folder." },
  { key: "MySQLExecutable", label: "MySQLExecutable", hint: "mysql.exe the database updater runs." },
];

/** How a value stands in the configs: all applied, some differ, or no config has the key. */
function Summary({ files, found }: { files: FileState[]; found: boolean }) {
  if (!found) return null;
  if (!files.length) return <span className="text-faint">No config has this key</span>;
  const differs = files.filter((f) => f.state === "differs");
  if (!differs.length) {
    const where = new Set(files.map((f) => f.file));
    return (
      <span className="flex items-center gap-1 text-ok">
        <CheckCircle2 className="size-3" /> Set in {where.size === 1 ? [...where][0] : `all ${where.size} configs that have it`}
      </span>
    );
  }
  return (
    <span className="text-warn" title={differs.map((f) => `${f.file}${f.key ? ` ${f.key}` : ""}: ${f.current}`).join("\n")}>
      Differs in {[...new Set(differs.map((f) => f.file))].join(", ")}
    </span>
  );
}

/** One setting in the grid: name (with its description in the tooltip), the control, its status in the configs. */
function Cell({ label, hint, status, action, className, children }: {
  label: string; hint: string; status?: ReactNode; action?: ReactNode; className?: string; children: ReactNode;
}) {
  return (
    <div className={cx("min-w-0", className)}>
      <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
        <span className="truncate">{label}</span>
        <span title={hint} className="shrink-0 text-faint hover:text-muted"><Info className="size-3.5" /></span>
        {action && <span className="ml-auto shrink-0">{action}</span>}
      </div>
      {children}
      {status && <div className="mt-1.5 text-xs">{status}</div>}
    </div>
  );
}

/** Config Files -> top: the values the panel keeps in every server config (paths + database connection). */
export function ConfigValues({ onApplied }: { onApplied: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: s } = useQuery({ queryKey: ["config-values"], queryFn: () => get<ValuesStatus>("/api/config-values"), refetchOnWindowFocus: true });
  const [paths, setPathsState] = useState<Record<PathKey, string> | null>(null);
  const [db, setDbState] = useState({ host: "", port: 3306, user: "", password: "" });
  const [saving, setSaving] = useState(false);
  // The fields follow the latest status (e.g. after choosing the AzerothCore folder or a deploy) until you edit one.
  const [edited, setEdited] = useState(false);
  const setPaths = (v: Record<PathKey, string>) => { setEdited(true); setPathsState(v); };
  const setDb = (v: typeof db) => { setEdited(true); setDbState(v); };
  // The saved password, once revealed with the eye button. Showing it isn't a change.
  const [revealed, setRevealed] = useState<string | null>(null);
  const reveal = async () => {
    const password = revealed ?? (await get<{ password: string }>("/api/config-values/password")).password;
    setRevealed(password);
    setDbState((d) => ({ ...d, password }));
  };
  // Hiding an unchanged saved password empties the field again: it then shows the fixed •••••••• placeholder.
  const hide = () => setDbState((d) => (d.password === revealed ? { ...d, password: "" } : d));

  useEffect(() => {
    if (s && !edited) {
      setPathsState({ DataDir: s.paths.DataDir.value, LogsDir: s.paths.LogsDir.value, MySQLExecutable: s.paths.MySQLExecutable.value });
      setDbState({ host: s.db.host || "127.0.0.1", port: s.db.port ?? 3306, user: s.db.user, password: "" });
    }
  }, [s, edited]);

  if (!s || !paths) return <Card className="p-5"><Spinner /></Card>;

  const newPassword = db.password && db.password !== revealed ? db.password : "";     // "" = keep the saved one
  const dbTouched = !!(db.user.trim() || newPassword || s.db.user);
  const pathsChanged = PATHS.some((p) => paths[p.key].trim() !== s.paths[p.key].value);
  const dbChanged = dbTouched && (db.host.trim() !== s.db.host || db.port !== s.db.port || db.user.trim() !== s.db.user || !!newPassword);
  const differs = PATHS.some((p) => s.paths[p.key].files.some((f) => f.state === "differs")) || (s.db.user !== "" && s.db.files.some((f) => f.state === "differs"));
  const dbIncomplete = dbTouched && (!db.host.trim() || !db.user.trim() || (!db.password && !s.db.password_set));

  const save = async () => {
    setSaving(true);
    try {
      const body = {
        paths: Object.fromEntries(PATHS.map((p) => [p.key, paths[p.key].trim()])),
        db: dbTouched ? { host: db.host.trim(), port: db.port, user: db.user.trim(), password: newPassword || null } : null,
      };
      const r = await put<{ applied: { file: string; changed: string[] }[]; status: ValuesStatus }>("/api/config-values", body);
      qc.setQueryData(["config-values"], r.status);
      setEdited(false);                                   // fields follow the new status again
      setRevealed(null);
      toast({
        tone: "ok",
        title: r.applied.length ? `Applied to ${r.applied.length} config${r.applied.length > 1 ? "s" : ""}` : "Saved",
        body: r.applied.length
          ? r.applied.map((a) => `${a.file}: ${a.changed.join(", ")}`).join("\n")
          : s.configs_found ? "All configs already had these values." : "No configs yet: deploy writes these values when it creates them.",
      });
      if (r.applied.length) onApplied();
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't save", body: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const reset = (key: PathKey) =>
    paths[key] !== s.paths[key].default && (
      <button className="text-faint hover:text-text" title={`Back to the default (${s.paths[key].default || "empty"})`}
        onClick={() => setPaths({ ...paths, [key]: s.paths[key].default })}>
        <RotateCcw className="size-3.5" />
      </button>
    );

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-3">
        <span className="mr-auto flex flex-wrap items-center gap-2 text-xs text-muted">
          {differs ? <Badge tone="warn" dot>Not applied everywhere</Badge> : s.configs_found ? <Badge tone="ok" dot>Applied</Badge> : <Badge tone="muted">No configs yet</Badge>}
          Save &amp; apply writes these into the server configs. After a deploy, apply them again; restart the servers afterwards.
        </span>
        {dbIncomplete && <span className="text-xs text-warn">Enter IP, account and password for the database connection.</span>}
        <Button size="sm" variant="primary" icon={<Save className="size-3.5" />} loading={saving}
          disabled={dbIncomplete || (!pathsChanged && !dbChanged && !differs)} onClick={save}>
          Save &amp; apply
        </Button>
      </div>
      <div className="space-y-4">
        <Card>
          <div className="flex items-center gap-2 border-b border-line px-4 py-2.5 text-[13px] font-semibold">
            <SlidersHorizontal className="size-4 text-accent" /> Paths
          </div>
          <div className="grid gap-x-4 gap-y-3 p-4 sm:grid-cols-2 xl:grid-cols-4">
            {PATHS.map((p) => (
              <Cell key={p.key} label={p.label} hint={p.hint} action={reset(p.key)} className={cx(p.key === "MySQLExecutable" && "sm:col-span-2")}
                status={<Summary files={s.paths[p.key].files} found={s.configs_found} />}>
                {p.key === "MySQLExecutable" ? (
                  <PathInput mode="file" ext=".exe" value={paths[p.key]} onChange={(v) => setPaths({ ...paths, [p.key]: v })} title="Choose mysql.exe" />
                ) : (
                  <Input className="font-mono" value={paths[p.key]} onChange={(e) => setPaths({ ...paths, [p.key]: e.target.value })} />
                )}
              </Cell>
            ))}
          </div>
        </Card>
        <Card>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line px-4 py-2.5">
            <span className="text-[13px] font-semibold">Database connection</span>
            <span className="text-xs text-faint">*DatabaseInfo · the MySQL login the servers use, same as in Database setup</span>
            <span className="ml-auto text-xs">
              {s.db.user ? (
                <span className="flex flex-wrap items-center gap-x-3">
                  <Summary files={s.db.files} found={s.configs_found} />
                  {s.db.source === "configs" && <span className="text-faint">Read from your configs</span>}
                </span>
              ) : <span className="text-faint">Not set: configs keep their own connection</span>}
            </span>
          </div>
          <div className="grid gap-x-4 gap-y-3 p-4 sm:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,2fr)_minmax(0,2fr)]">
            <Cell label="IP address" hint="Where MySQL listens (127.0.0.1 = this PC)."><Input className="font-mono" value={db.host} onChange={(e) => setDb({ ...db, host: e.target.value })} /></Cell>
            <Cell label="Port" hint="MySQL's port (my.ini)."><Input type="number" min={1} max={65535} value={db.port} onChange={(e) => setDb({ ...db, port: Number(e.target.value) })} /></Cell>
            <Cell label="Account" hint="The MySQL account the servers log in with."><Input value={db.user} onChange={(e) => setDb({ ...db, user: e.target.value })} autoComplete="off" /></Cell>
            <Cell label="Password" hint="Shown with the eye button. Empty keeps the saved one.">
              <PasswordInput value={db.password} onChange={(e) => setDb({ ...db, password: e.target.value })}
                placeholder={s.db.password_set ? "••••••••" : ""} autoComplete="new-password"
                onReveal={s.db.password_set ? reveal : undefined} onHide={hide} />
            </Cell>
          </div>
        </Card>
      </div>
    </div>
  );
}
