import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, RefreshCw } from "lucide-react";
import { get, post } from "../lib/api";
import { useToolchain } from "../lib/build";
import { useStatus } from "../lib/hooks";
import { JobOutput, ProgressBar, type JobBase } from "./JobOutput";
import { Button, Callout, Card, CardHeader, cx, Field, Input, Select, Spinner, useToast } from "./ui";

interface Preset {
  key: string;
  label: string;
  url: string;
  branch: string;
  modules: { name: string; url: string; branch: string }[];
}

interface CloneJob extends JobBase {
  detail?: string | null;
  url: string;
  branch: string;
  modules?: string[];
}

const STEPS: Record<string, string> = { source: "Download source", modules: "Modules" };
const DESCRIPTION: Record<string, string> = {
  official: "The official AzerothCore 3.3.5a core.",
  playerbots: "The playerbots fork of the core, plus the mod-playerbots module it needs.",
  custom: "Any repository: your own fork or someone else's.",
};

/** Setup -> Source code: clone AzerothCore (official, playerbots fork or any URL) into <AzerothCore folder>\source. */
export function SourceSetup() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: status } = useStatus();
  const { data: tc } = useToolchain();
  const { data: presets } = useQuery({ queryKey: ["source-presets"], queryFn: () => get<Preset[]>("/api/source/presets"), staleTime: Infinity });
  const [preset, setPreset] = useState("official");
  const [url, setUrl] = useState("");
  const [branch, setBranch] = useState("");
  const [branches, setBranches] = useState<{ list: string[]; error: string | null; loading: boolean }>({ list: [], error: null, loading: false });
  const [job, setJob] = useState<number | null>(null);
  const [starting, setStarting] = useState(false);

  // Follow a clone that is still running from before a reload (kept after it ends, to show the result).
  const runningId = status?.source?.id;
  useEffect(() => {
    if (runningId != null) setJob(runningId);
  }, [runningId]);

  const chosen = presets?.find((p) => p.key === preset);
  useEffect(() => {
    if (chosen) {
      setUrl(chosen.url);
      setBranch(chosen.branch);
      setBranches({ list: [], error: null, loading: false });
    }
  }, [chosen]);

  if (!presets) return <Card className="p-5"><Spinner /></Card>;

  const busy = !!status?.source || !!status?.build || !!status?.modules;
  const target = tc?.workspace.source ?? null;          // fixed place in the AzerothCore folder
  const present = !!tc?.workspace.source_valid;
  // Why Clone is disabled, first reason only (null: it can run).
  const blocked = !tc ? "Checking…"
    : !target ? "Choose your AzerothCore folder above first."
    : present ? "The source is already there. Update it on Compilation; to clone another one, delete or rename that folder first."
    : busy ? "Wait for the running build, module or clone job."
    : !url.trim() || !branch.trim() ? "Enter the repository URL and branch."
    : null;

  const loadBranches = async () => {
    setBranches({ list: [], error: null, loading: true });
    try {
      const r = await get<{ default: string | null; branches: string[] }>(`/api/source/branches?url=${encodeURIComponent(url.trim())}`);
      setBranches({ list: r.branches, error: null, loading: false });
      if (!r.branches.includes(branch) && r.default) setBranch(r.default);
    } catch (e) {
      setBranches({ list: [], error: (e as Error).message, loading: false });
    }
  };

  const start = async () => {
    setStarting(true);
    try {
      const r = await post<{ job_id: number }>("/api/source/clone", { preset, url: url.trim(), branch: branch.trim() });
      setJob(r.job_id);
      qc.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      toast({ tone: "bad", title: "Clone didn't start", body: (e as Error).message });
    } finally {
      setStarting(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Source code"
        subtitle="Download AzerothCore with git into the source folder that Compilation builds."
      />
      <div className="space-y-4 p-4">
            <div className="grid gap-3 md:grid-cols-3">
              {[...presets.map((p) => ({ key: p.key, label: p.label })), { key: "custom", label: "Custom repository" }].map((p) => (
                <button key={p.key} onClick={() => setPreset(p.key)}
                  className={cx("rounded-lg border px-4 py-3 text-left transition-colors", preset === p.key ? "border-accent bg-accent-soft" : "border-line hover:border-line-strong")}>
                  <div className="text-[13px] font-medium">{p.label}</div>
                  <div className="mt-0.5 text-xs text-muted">{DESCRIPTION[p.key]}</div>
                </button>
              ))}
            </div>
            <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_16rem]">
              <Field label="Repository URL">
                <Input className="font-mono" value={url} disabled={preset !== "custom"} placeholder="https://github.com/owner/azerothcore-wotlk.git"
                  onChange={(e) => { setUrl(e.target.value); setBranches({ list: [], error: null, loading: false }); }} />
              </Field>
              <Field label="Branch" hint={branches.list.length ? `${branches.list.length} branches in this repository` : undefined}>
                <div className="flex gap-2">
                  {branches.list.length ? (
                    <Select value={branch} onChange={(e) => setBranch(e.target.value)}>
                      {!branches.list.includes(branch) && <option value={branch}>{branch}</option>}
                      {branches.list.map((b) => <option key={b} value={b}>{b}</option>)}
                    </Select>
                  ) : (
                    <Input value={branch} onChange={(e) => setBranch(e.target.value)} />
                  )}
                  <Button variant="ghost" icon={<RefreshCw className={cx("size-4", branches.loading && "animate-spin")} />} disabled={!url.trim().startsWith("https://")}
                    onClick={loadBranches} title="Load the branches of this repository" />
                </div>
              </Field>
            </div>
            {branches.error && <Callout tone="bad">{branches.error}</Callout>}
            {branches.list.length > 0 && !branches.list.includes(branch) && <Callout tone="warn">The branch "{branch}" doesn't exist in this repository.</Callout>}
            {chosen && chosen.modules.length > 0 && (
              <p className="text-xs text-muted">Also installs {chosen.modules.map((m) => m.name).join(", ")} into modules\, which this repository needs.</p>
            )}
            {target && <p className="text-xs text-muted">Clones into <span className="font-mono text-text">{target}</span></p>}
            <div className="flex flex-wrap items-center gap-2">
              <Button variant="primary" icon={<Download className="size-4" />} loading={starting} disabled={!!blocked} onClick={start}>
                Clone
              </Button>
              {blocked && job == null && <span className="text-xs text-muted">{blocked}</span>}
            </div>

        {job != null && (
          <JobOutput<CloneJob>
            key={job}
            base="/api/source"
            jobId={job}
            steps={(j) => ["source", ...(j.modules?.length ? ["modules"] : [])]}
            stepLabels={STEPS}
            subtitle={(j) => `Clone ${j.url} (${j.branch})`}
            progress={(j) => (j.status === "running" ? <ProgressBar value={j.progress}>{j.detail ? <span>{j.detail}</span> : null}</ProgressBar> : null)}
            summary={() => ({ tone: "ok", text: "Source ready. Compilation now builds it." })}
            invalidate={[["toolchain"], ["db-setup"]]}
          />
        )}
      </div>
    </Card>
  );
}
