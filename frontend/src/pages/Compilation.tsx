import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowUpCircle, GitBranch, Hammer, Link2Off, Package, RefreshCw, Rocket,
} from "lucide-react";
import { post } from "../lib/api";
import { useToolchain, type BuildJob, type BuildOptions, type Toolchain } from "../lib/build";
import { dateTime } from "../lib/format";
import { useStatus } from "../lib/hooks";
import { JobOutput, ProgressBar } from "../components/JobOutput";
import { Badge, Button, Callout, Card, CardHeader, cx, Field, Input, PageHeader, Segmented, Select, Spinner, useToast } from "../components/ui";

const STEP_LABEL: Record<string, string> = { pull: "Pull", configure: "Configure", build: "Compile", deploy: "Deploy" };
const TYPE_LABEL: Record<string, string> = { build: "Build", deploy: "Deploy", pull: "Source update" };

/** files_total counts every source file; a build in an existing build folder only compiles what changed. */
function filesLabel(j: BuildJob): string {
  const done = j.files_done ?? 0, total = j.files_total ?? 0;
  if (j.status === "completed" && done < total) return `${done} files compiled · ${total - done} already up to date`;
  if (j.fresh === false) return `${done} files compiled (only what changed)`;
  return `${done} / ${total} files`;
}
const OPTION_LABEL: Record<string, { label: string; hint: string }> = {
  TOOLS_BUILD: { label: "Tools", hint: "Extractors for maps, vmaps and mmaps (all), or none" },
  SCRIPTS: { label: "Scripts", hint: "static = built into worldserver (normal)" },
  MODULES: { label: "Modules", hint: "static = built into worldserver (normal)" },
};

// ---- source ------------------------------------------------------------------------------------------

/** One bar for the source: its git revision, the modules that get compiled in, and Pull Latest Source. */
function SourceBar({ tc, running, onStarted }: { tc: Toolchain; running: boolean; onStarted: (id: number) => void }) {
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  const ws = tc.workspace;
  const rev = ws.revision;
  const git = tc.items.find((i) => i.key === "git");
  const usable = ws.source_valid && git?.status === "ok" && rev?.git;
  const pull = async () => {
    setBusy(true);
    try {
      const r = await post<{ job_id: number }>("/api/build/pull");
      onStarted(r.job_id);
      qc.invalidateQueries({ queryKey: ["build-jobs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      toast({ tone: "bad", title: "Pull didn't start", body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="px-4 py-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <GitBranch className="size-5 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          {ws.source_valid && rev?.git ? (
            <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[13px]">
              <span className="font-semibold">AzerothCore</span>
              <span className="text-muted">{rev.branch}</span>
              <span className="font-mono text-xs text-muted" title={ws.source ?? ""}>@{rev.commit}</span>
              <span className="truncate text-muted">{rev.subject}</span>
              {rev.date && <span className="text-xs text-faint">{dateTime(rev.date)}</span>}
              {rev.dirty && <Badge tone="warn">local changes</Badge>}
            </div>
          ) : ws.source_valid ? (
            <div className="text-[13px] font-semibold">AzerothCore <span className="font-normal text-muted">(not a git checkout)</span></div>
          ) : (
            <div className="text-[13px] text-bad">No AzerothCore source yet. Clone it on the <a className="underline" href="#/setup">Setup</a> page.</div>
          )}
          {ws.source_valid && (
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
              {ws.modules.length ? ws.modules.map((m) => (
                <span key={m.name}
                  className={cx("inline-flex items-center gap-1 rounded-md border px-2 py-0.5", m.broken ? "border-bad-line bg-bad-soft text-bad" : "border-line bg-card-2 text-muted")}
                  title={m.broken ? `Links to ${m.link}, which no longer exists` : m.git ? `${m.branch}@${m.commit}${m.dirty ? " (local changes)" : ""}` : m.name}>
                  {m.broken ? <Link2Off className="size-3" /> : <Package className="size-3" />}
                  <span className="text-text">{m.name}</span>
                  {m.dirty && <span className="size-1.5 rounded-full bg-warn" />}
                </span>
              )) : <span className="text-faint">No modules</span>}
              <a href="#/modules" className="ml-1 text-faint underline hover:text-text">Modules</a>
            </div>
          )}
        </div>
        <Button icon={<ArrowUpCircle className="size-4" />} loading={busy} disabled={!usable || running} onClick={pull}
          title={usable ? "Pull the latest commits from the AzerothCore git repository" : "Needs Git and a source folder that is a git checkout"}>
          Pull Latest Source
        </Button>
      </div>
    </Card>
  );
}

// ---- build configuration ------------------------------------------------------------------------------

function Check({ checked, onChange, label, hint, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string; disabled?: boolean }) {
  return (
    <label className={cx("flex items-start gap-2.5", disabled ? "opacity-45" : "cursor-pointer")}>
      <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="block text-[13px]">{label}</span>
        {hint && <span className="block text-xs text-faint">{hint}</span>}
      </span>
    </label>
  );
}

function ConfigCard({ tc, running, onStarted }: { tc: Toolchain; running: boolean; onStarted: (id: number) => void }) {
  const [o, setO] = useState<BuildOptions>(tc.options);
  const [starting, setStarting] = useState<"build" | "deploy" | null>(null);
  const toast = useToast();
  const qc = useQueryClient();
  const set = <K extends keyof BuildOptions>(k: K, v: BuildOptions[K]) => setO((s) => ({ ...s, [k]: v }));
  const choices = tc.workspace.choices;
  const canDeploy = tc.built.includes(o.config);

  const start = async (kind: "build" | "deploy") => {
    setStarting(kind);
    try {
      const r = kind === "build"
        ? await post<{ job_id: number }>("/api/build/run", o)
        : await post<{ job_id: number }>("/api/build/deploy", { config: o.config });
      onStarted(r.job_id);
      qc.invalidateQueries({ queryKey: ["build-jobs"] });
      qc.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      toast({ tone: "bad", title: kind === "build" ? "Build didn't start" : "Deploy didn't start", body: (e as Error).message });
    } finally {
      setStarting(null);
    }
  };

  return (
    <Card>
      <CardHeader title="Build Configuration" subtitle="Choose how to build and what to do afterwards" />
      <div className="space-y-4 p-4">
        <Field label="Build type" hint="RelWithDebInfo is what AzerothCore recommends: fast, and crash logs stay readable.">
          <Segmented value={o.config} options={tc.configs.map((c) => ({ value: c, label: c }))} onChange={(v) => set("config", v)} />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Object.entries(OPTION_LABEL).map(([key, meta]) =>
            choices[key] ? (
              <Field key={key} label={meta.label} hint={meta.hint}>
                <Select value={(o[key as keyof BuildOptions] as string) ?? ""} onChange={(e) => set(key as keyof BuildOptions, e.target.value as never)}>
                  {choices[key].choices.map((c) => <option key={c} value={c}>{c}</option>)}
                </Select>
              </Field>
            ) : null,
          )}
          <Field label="Parallel jobs" hint={tc.cpu_threads
            ? `CPU threads to compile with. This PC has ${tc.cpu_threads} (the default); fewer keeps it more usable while compiling.`
            : "Number of CPU threads to compile with"}>
            <Input type="number" min={1} max={256} value={o.jobs} onChange={(e) => set("jobs", Math.max(1, Number(e.target.value) || 1))} />
          </Field>
        </div>
        <div className="flex flex-wrap gap-x-10 gap-y-3 border-t border-line pt-4">
          <Check checked={o.clean} onChange={(v) => set("clean", v)} label="Clean build" hint="Deletes the build folder first (much slower)" />
          <Check checked={o.deploy} onChange={(v) => set("deploy", v)} label="Deploy when done" hint="Install into the server folder (servers must be stopped)" />
        </div>
        {!tc.ready && (
          <Callout tone="bad">
            <div className="space-y-1">{tc.problems.map((p, i) => <div key={i}>{p}</div>)}</div>
          </Callout>
        )}
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" icon={<Hammer className="size-4" />} loading={starting === "build"} disabled={!tc.ready || running} onClick={() => start("build")}>
            Start Build
          </Button>
          <Button icon={<Rocket className="size-4" />} loading={starting === "deploy"} disabled={!tc.deploy_ready || running || !canDeploy} onClick={() => start("deploy")}
            title={canDeploy ? "Deploy the last compiled binaries without compiling" : `Nothing compiled as ${o.config} yet`}>
            Deploy only
          </Button>
        </div>
      </div>
    </Card>
  );
}

// ---- output -----------------------------------------------------------------------------------------------

function OutputCard({ jobId }: { jobId: number }) {
  return (
    <JobOutput<BuildJob>
      base="/api/build"
      jobId={jobId}
      steps={(j) => (j.type === "deploy" ? ["deploy"] : j.type === "pull" ? ["pull"] : ["configure", "build", ...(j.options.deploy ? ["deploy"] : [])])}
      stepLabels={STEP_LABEL}
      subtitle={(j) => `${TYPE_LABEL[j.type]}${j.options.config ? ` · ${j.options.config}` : ""}`}
      progress={(j) =>
        j.step === "build" || j.projects_total > 0 ? (
          <ProgressBar value={j.status === "completed" ? 100 : j.progress} failed={j.status === "failed"}>
            {!!j.files_total && <span>{filesLabel(j)}</span>}
            <span>{j.projects_done} / {j.projects_total} projects</span>
            <span className={cx(j.warnings > 0 && "text-warn")}>{j.warnings} warnings</span>
            <span className={cx(j.errors > 0 && "text-bad")}>{j.errors} errors</span>
          </ProgressBar>
        ) : null
      }
      summary={(j) =>
        j.type === "pull"
          ? { tone: "ok", text: j.commits ? `${j.commits} new commit(s). Start a build to use them.` : "Already up to date." }
          : j.deployed && j.configs?.length
            ? { tone: "ok", text: "Built and deployed. Before starting the servers, go to Config Files." }
          : j.deployed ? { tone: "ok", text: "Built and deployed. Start the servers to use the new binaries." }
          : j.options.deploy || j.type === "deploy" ? { tone: "warn", text: "Built, but not deployed (see the log)." }
          : { tone: "ok", text: "Built. Click Deploy only to install it into the server folder." }
      }
      invalidate={[["build-jobs"], ["toolchain"]]}
    />
  );
}

// ---- page --------------------------------------------------------------------------------------------------

export function Compilation() {
  const { data: tc, isLoading, isFetching, refetch, error } = useToolchain();
  const { data: status } = useStatus();
  // The output box shows the running job, or else the latest one.
  const [selected, setSelected] = useState<number | null>(null);
  const runningId = status?.build?.id ?? null;
  // The output box shows what runs now (or what you just started), never older jobs.
  const shown = runningId ?? selected;

  useEffect(() => {
    if (runningId) setSelected(runningId);
  }, [runningId]);

  if (isLoading) return <Spinner />;
  if (error || !tc) return <Callout tone="bad">{(error as Error)?.message ?? "Couldn't read the build setup."}</Callout>;

  return (
    <>
      <PageHeader
        title="Compilation"
        subtitle="Build AzerothCore from source and deploy it into the server folder"
        right={<Button size="sm" variant="ghost" icon={<RefreshCw className={cx("size-3.5", isFetching && "animate-spin")} />} onClick={() => refetch()}>Re-check</Button>}
      />
      <div className="mb-4">
        <SourceBar tc={tc} running={!!runningId} onStarted={setSelected} />
      </div>
      <ConfigCard key={JSON.stringify(tc.options)} tc={tc} running={!!runningId} onStarted={setSelected} />
      {shown != null && (
        <div className="mt-4">
          <OutputCard key={shown} jobId={shown} />
        </div>
      )}
    </>
  );
}
