import { useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Download, HardDrive, Play, XCircle } from "lucide-react";
import { get, post } from "../lib/api";
import { useStatus } from "../lib/hooks";
import { JobOutput, ProgressBar, type JobBase } from "../components/JobOutput";
import { Badge, Button, Callout, Card, CardHeader, cx, Field, PageHeader, Spinner, useConfirm, useToast } from "../components/ui";
import { PathInput } from "../components/PathPicker";

type DataType = "dbc" | "maps" | "vmaps" | "mmaps";

interface DataStatus {
  data_dir: string;
  tiles: { key: DataType; present: boolean; files: number; required: boolean }[];
  installed_version: string | null;
  pinned_version: string | null;
  ready: boolean;
  tools: Record<string, boolean>;
  client_dir: string;
  world_running: boolean;
  busy: boolean;
}

interface DataJob extends JobBase {
  type: "download" | "extract";
  version?: string;
  types?: DataType[];
  detail?: string | null;
  downloaded?: number;
  total?: number;
  /** Download speed in bytes per second (last few seconds). */
  speed?: number;
}

const LABEL: Record<DataType, string> = { dbc: "DBC", maps: "Maps", vmaps: "VMaps", mmaps: "MMaps" };
const STEP_LABEL: Record<string, string> = {
  download: "Download", extract: "Unpack", install: "Install", dbc_maps: "DBC & Maps", vmaps: "VMaps", mmaps: "MMaps",
};
/** "12 min", "45 s" */
function remaining(seconds: number): string {
  return seconds >= 90 ? `${Math.round(seconds / 60)} min` : `${Math.max(1, Math.round(seconds))} s`;
}

const MB = 1024 * 1024;

// ---- status ----------------------------------------------------------------------------------------------

function StatusCard({ s }: { s: DataStatus }) {
  // Only a downloaded release (v20.0, ...) can be compared; extracted data says "client-12340".
  const fromClient = s.installed_version?.startsWith("client-");
  const versionMismatch = s.pinned_version && s.installed_version && !fromClient && s.pinned_version !== s.installed_version;
  return (
    <Card>
      <CardHeader
        title="Client Data Status"
        subtitle={<span className="font-mono">{s.data_dir}</span>}
        right={s.ready ? <Badge tone="ok" dot>Ready</Badge> : <Badge tone="bad" dot>Incomplete</Badge>}
      />
      <div className="space-y-3 p-4">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {s.tiles.map((t) => {
            const tone = t.present ? "ok" : t.required ? "bad" : "warn";
            return (
              <div key={t.key} className={cx("rounded-lg border px-4 py-3",
                tone === "ok" ? "border-ok-line bg-ok-soft" : tone === "bad" ? "border-bad-line bg-bad-soft" : "border-warn-line bg-warn-soft")}>
                <div className={cx("flex items-center gap-2 text-[13px] font-semibold", tone === "ok" ? "text-ok" : tone === "bad" ? "text-bad" : "text-warn")}>
                  {tone === "ok" ? <CheckCircle2 className="size-4" /> : tone === "bad" ? <XCircle className="size-4" /> : <AlertTriangle className="size-4" />}
                  {LABEL[t.key]}
                </div>
                <div className="mt-1 text-xs text-muted">
                  {t.present ? `Present · ${t.files.toLocaleString()} files` : t.required ? "Missing" : "Optional · not present"}
                </div>
              </div>
            );
          })}
        </div>
        <div className="flex flex-wrap gap-x-6 text-xs text-muted">
          <span>
            {fromClient ? "Extracted from a client (build " : "Installed release: "}
            <span className="text-text">{fromClient ? s.installed_version!.slice("client-".length) : s.installed_version ?? "unknown"}</span>
            {fromClient && ")"}
          </span>
          {s.pinned_version && <span>Your AzerothCore source expects: <span className="text-text">{s.pinned_version}</span></span>}
        </div>
        {!s.ready && <Callout tone="warn">Client data is required before starting the servers. Use the options below to get it.</Callout>}
        {versionMismatch && (
          <Callout tone="warn">
            The installed data ({s.installed_version}) is not the release your source expects ({s.pinned_version}). Download it again so maps match the core.
          </Callout>
        )}
      </div>
    </Card>
  );
}

// ---- method choice -----------------------------------------------------------------------------------------

function MethodCard({ active, onClick, title, subtitle, icon, points }: { active: boolean; onClick: () => void; title: string; subtitle: string; icon: ReactNode; points: string[] }) {
  return (
    <button
      onClick={onClick}
      className={cx("h-full w-full rounded-xl border bg-card p-5 text-left transition-colors", active ? "border-accent ring-1 ring-accent" : "border-line hover:border-line-strong")}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-[13px] font-semibold">{title}</div>
          <div className="mt-0.5 text-xs text-muted">{subtitle}</div>
        </div>
        <span className={cx(active ? "text-accent" : "text-muted")}>{icon}</span>
      </div>
      <ul className="mt-4 space-y-1.5 text-[13px] text-muted">
        {points.map((p) => <li key={p}>• {p}</li>)}
      </ul>
    </button>
  );
}

function DownloadPanel({ s, blocked, onStarted }: { s: DataStatus; blocked: string | null; onStarted: (id: number) => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const confirm = useConfirm();
  // The release the source expects is already installed and complete: downloading it again changes nothing.
  const installed = !!s.pinned_version && s.installed_version === s.pinned_version && s.ready;
  const start = async () => {
    if (installed && !(await confirm({
      title: "Download again?",
      body: `Client data ${s.pinned_version} is already installed. Downloading it again (about 1.2 GB) replaces it with the same files.`,
      confirm: "Download again",
    }))) return;
    setBusy(true);
    try {
      onStarted((await post<{ job_id: number }>("/api/client-data/download")).job_id);
    } catch (e) {
      toast({ tone: "bad", title: "Download didn't start", body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card>
      <CardHeader title="Download Client Data" subtitle="Pre-extracted data from wowgaming/client-data releases" />
      <div className="space-y-4 p-4">
        <p className="text-[13px] text-muted">
          This downloads <span className="font-mono text-text">data.zip</span>
          {s.pinned_version ? <> (release <span className="text-text">{s.pinned_version}</span>, the one your source expects)</> : " (latest release)"} from
          GitHub and unpacks it into your data folder. The current data is replaced only after everything has been unpacked.
          An interrupted download continues where it stopped.
        </p>
        {blocked && <Callout tone="warn">{blocked}</Callout>}
        <Button variant="primary" icon={<Download className="size-4" />} loading={busy} disabled={!!blocked} onClick={start}>
          {installed ? "Download Again" : "Download Data"}
        </Button>
        {installed && <span className="ml-3 text-xs text-muted">{s.pinned_version} is already installed.</span>}
      </div>
    </Card>
  );
}

function ExtractPanel({ s, blocked, onStarted }: { s: DataStatus; blocked: string | null; onStarted: (id: number) => void }) {
  const [client, setClient] = useState(s.client_dir);
  const [types, setTypes] = useState<Record<DataType, boolean>>({ dbc: true, maps: true, vmaps: true, mmaps: false });
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const chosen = (Object.keys(types) as DataType[]).filter((t) => types[t]);
  const needed = [
    ...(types.dbc || types.maps ? ["map_extractor.exe"] : []),
    ...(types.vmaps ? ["vmap4_extractor.exe", "vmap4_assembler.exe"] : []),
    ...(types.mmaps ? ["mmaps_generator.exe"] : []),
  ].filter((t) => !s.tools[t]);

  const start = async () => {
    setBusy(true);
    try {
      onStarted((await post<{ job_id: number }>("/api/client-data/extract", { client_dir: client, types: chosen })).job_id);
    } catch (e) {
      toast({ tone: "bad", title: "Extraction didn't start", body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const box = (t: DataType, hint: string) => (
    <label key={t} className="flex cursor-pointer items-start gap-2.5">
      <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={types[t]} onChange={(e) => setTypes((x) => ({ ...x, [t]: e.target.checked }))} />
      <span>
        <span className="block text-[13px]">{LABEL[t]}</span>
        <span className="block text-xs text-faint">{hint}</span>
      </span>
    </label>
  );

  return (
    <Card>
      <CardHeader title="Extract from Local Client" subtitle="Uses the extractor tools in your server folder" />
      <div className="space-y-4 p-4">
        <Field label="Client folder" hint="The folder with Wow.exe (3.3.5a, build 12340) and Data\">
          <PathInput value={client} onChange={setClient} placeholder="C:\Games\World of Warcraft 3.3.5a" title="Choose your WoW 3.3.5a folder" />
        </Field>
        <div>
          <div className="mb-2 text-xs font-medium text-muted">Data types to extract</div>
          <div className="grid gap-3 sm:grid-cols-2">
            {box("dbc", "Required · includes Cameras")}
            {box("maps", "Required")}
            {box("vmaps", "Required · line of sight and heights")}
            {box("mmaps", "Optional · creature pathfinding")}
          </div>
        </div>
        {types.mmaps && <Callout tone="warn">Generating MMaps can take hours. Downloading the pre-extracted data is much faster.</Callout>}
        {needed.length > 0 && <Callout tone="bad">{needed.join(", ")} not found in the server folder. Compile with Tools = all and deploy first.</Callout>}
        {blocked && <Callout tone="warn">{blocked}</Callout>}
        <Button variant="primary" icon={<Play className="size-4" />} loading={busy} disabled={!!blocked || !chosen.length || needed.length > 0 || !client.trim()} onClick={start}>
          Start Extraction
        </Button>
      </div>
    </Card>
  );
}

// ---- page ----------------------------------------------------------------------------------------------------

export function DataExtraction() {
  const { data: s, isLoading, error } = useQuery({ queryKey: ["client-data"], queryFn: () => get<DataStatus>("/api/client-data") });
  const { data: status } = useStatus();
  const [method, setMethod] = useState<"download" | "extract">("download");
  const [selected, setSelected] = useState<number | null>(null);
  const qc = useQueryClient();
  const runningId = status?.data?.id ?? null;
  const shown = runningId ?? selected;

  if (isLoading) return <Spinner />;
  if (error || !s) return <Callout tone="bad">{(error as Error)?.message ?? "Couldn't read the client data status."}</Callout>;

  const blocked = runningId ? "A download or extraction is running." : s.world_running ? "Stop Worldserver first: its data folders get replaced." : null;
  const started = (id: number) => {
    setSelected(id);
    qc.invalidateQueries({ queryKey: ["client-data-jobs"] });
    qc.invalidateQueries({ queryKey: ["status"] });
  };

  return (
    <>
      <PageHeader title="Data Extraction" subtitle="Maps, vmaps, mmaps and DBC files the worldserver needs" />
      <div className="space-y-4">
        <StatusCard s={s} />
        <div className="grid gap-4 xl:grid-cols-2">
          <MethodCard
            active={method === "download"}
            onClick={() => setMethod("download")}
            title="Download Pre-Extracted Data"
            subtitle="Recommended - Fast and easy"
            icon={<Download className="size-4" />}
            points={["Downloads ready-to-use data (about 1.2 GB)", "Includes DBC, Maps, VMaps and MMaps", "The release your AzerothCore source expects", "No client installation required"]}
          />
          <MethodCard
            active={method === "extract"}
            onClick={() => setMethod("extract")}
            title="Extract from Local Client"
            subtitle="For users with a WoW 3.3.5a client"
            icon={<HardDrive className="size-4" />}
            points={["Requires a World of Warcraft 3.3.5a (12340) client", "Choose which data types to extract", "MMaps generation can take hours", "Useful for custom data or an offline setup"]}
          />
        </div>
        {method === "download" ? <DownloadPanel s={s} blocked={blocked} onStarted={started} /> : <ExtractPanel s={s} blocked={blocked} onStarted={started} />}
        {shown != null && (
          <JobOutput<DataJob>
            key={shown}
            base="/api/client-data"
            jobId={shown}
            steps={(j) => (j.type === "download" ? ["download", "extract", "install"]
              : [...(j.types?.some((t) => t === "dbc" || t === "maps") ? ["dbc_maps"] : []), ...(j.types ?? []).filter((t) => t === "vmaps" || t === "mmaps"), "install"])}
            stepLabels={STEP_LABEL}
            subtitle={(j) => (j.type === "download" ? `Download ${j.version ?? ""}` : `Extract ${(j.types ?? []).map((t) => LABEL[t]).join(", ")}`)}
            progress={(j) => (j.status === "running" ? (
              <ProgressBar value={j.progress}>
                {j.step === "download" && j.total ? (
                  <span>
                    {Math.round((j.downloaded ?? 0) / MB)} / {Math.round(j.total / MB)} MB
                    {j.speed ? ` · ${(j.speed / MB).toFixed(1)} MB/s · ${remaining((j.total - (j.downloaded ?? 0)) / j.speed)} left` : ""}
                  </span>
                ) : null}
                {j.detail ? <span>{j.detail}</span> : null}
              </ProgressBar>
            ) : null)}
            summary={(j) => ({ tone: "ok", text: j.type === "download" ? `Client data ${j.version ?? ""} installed.` : `Extracted ${(j.types ?? []).map((t) => LABEL[t]).join(", ")}.` })}
            invalidate={[["client-data"], ["client-data-jobs"]]}
          />
        )}
      </div>
    </>
  );
}
