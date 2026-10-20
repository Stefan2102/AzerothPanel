import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Ban, Download } from "lucide-react";
import { get, post } from "../lib/api";
import { dateTime, duration } from "../lib/format";
import { Button, Callout, Card, CardHeader, cx, useToast } from "./ui";

const MAX_LINES = 5000;

/** The fields every job record has (backend/services/jobs.py); pages extend it. */
export interface JobBase {
  id: number;
  type: string;
  status: "running" | "completed" | "failed" | "cancelled";
  started: number;
  finished: number | null;
  error: string | null;
  step: string | null;
  progress: number;
  log?: string[];
  log_first?: number;
  log_total?: number;
}

function lineClass(l: string): string | false {
  if (l.startsWith("[step]")) return "font-semibold text-accent-text";
  if (l.startsWith("[done]")) return "text-ok";
  if (l.startsWith("[ERROR]") || /: (fatal )?error [A-Z]+\d+|^CMake Error|: error MSB\d+|^\s*ERROR \d+ \(/i.test(l)) return "text-[#f27474]";
  if (l.startsWith("[WARN]") || /: warning [A-Z]+\d+|^CMake Warning/i.test(l)) return "text-[#e9b44c]";
  if (l.startsWith("> ")) return "text-[#8fb8ff]";
  return false;
}

export function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

/**
 * Live output of one job: step chips, optional progress block, result, and the log
 * (polled incrementally with ?after=, so long logs stay cheap). With console={false} only the status is shown;
 * the full log is still downloadable.
 */
export function JobOutput<J extends JobBase>({
  base, jobId, steps, stepLabels, subtitle, progress, summary, invalidate, console = true,
}: {
  base: string;                                    // e.g. "/api/build"
  jobId: number;
  steps: (job: J) => string[];
  stepLabels: Record<string, string>;
  subtitle: (job: J) => string;
  progress?: (job: J) => ReactNode;
  summary: (job: J) => { tone: "ok" | "warn"; text: ReactNode };
  invalidate: string[][];                          // query keys to refresh when the job ends
  console?: boolean;                               // show the live log box
}) {
  const [job, setJob] = useState<J | null>(null);
  const [lines, setLines] = useState<string[]>([]);
  const box = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const qc = useQueryClient();
  const toast = useToast();
  const running = job?.status === "running";
  const now = useNow(running);
  const invalidateKey = JSON.stringify(invalidate);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    let after = 0;
    setLines([]);
    setJob(null);
    stick.current = true;
    const tick = async () => {
      try {
        const j = await get<J>(`${base}/jobs/${jobId}?after=${after}`);
        if (stop) return;
        const gap = (j.log_first ?? 0) > after ? [`… ${(j.log_first ?? 0) - after} earlier lines are in the downloadable log`] : [];
        if (console && (gap.length || j.log?.length)) setLines((prev) => [...prev, ...gap, ...(j.log ?? [])].slice(-MAX_LINES));
        after = j.log_total ?? after;
        setJob(j);
        if (j.status === "running") timer = setTimeout(tick, 1000);
        else for (const key of JSON.parse(invalidateKey) as string[][]) qc.invalidateQueries({ queryKey: key });
      } catch {
        if (!stop) timer = setTimeout(tick, 3000);
      }
    };
    tick();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [base, jobId, qc, invalidateKey, console]);

  useEffect(() => {
    if (stick.current && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [lines]);

  const cancel = async () => {
    try {
      await post(`${base}/jobs/${jobId}/cancel`);
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't cancel", body: (e as Error).message });
    }
  };

  const list = job ? steps(job) : [];
  const current = job?.step === "done" ? list.length : list.indexOf(job?.step ?? "");
  const elapsed = job ? (job.finished ?? now) - job.started : 0;
  const result = job?.status === "completed" ? summary(job) : null;

  return (
    <Card>
      <CardHeader
        title={console ? "Output" : "Status"}
        subtitle={job ? `${subtitle(job)} · started ${dateTime(job.started)}` : "Loading…"}
        right={
          <div className="flex items-center gap-2">
            {running && <Button size="sm" variant="danger" icon={<Ban className="size-3.5" />} onClick={cancel}>Cancel</Button>}
            <a href={`${base}/jobs/${jobId}/log`} className="inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-xs text-muted hover:bg-card-2 hover:text-text">
              <Download className="size-3.5" /> Log
            </a>
          </div>
        }
      />
      {job && (
        <div className={cx("space-y-3 px-4 py-3", console && "border-b border-line")}>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {list.map((s, i) => (
              <span key={s} className={cx("rounded-full border px-2.5 py-0.5",
                i < current || (job.status === "completed" && i <= current) ? "border-ok-line bg-ok-soft text-ok"
                  : i === current && running ? "border-accent bg-accent-soft text-accent-text"
                  : i === current && job.status !== "completed" ? "border-bad-line bg-bad-soft text-bad"
                  : "border-line text-faint")}>
                {stepLabels[s] ?? s}
              </span>
            ))}
            <span className="ml-auto text-muted">{duration(elapsed)}</span>
          </div>
          {progress?.(job)}
          {result && <Callout tone={result.tone}>{result.text}</Callout>}
          {job.status === "failed" && job.error && <Callout tone="bad">{job.error}</Callout>}
          {job.status === "cancelled" && <Callout tone="warn">Cancelled.</Callout>}
        </div>
      )}
      {console && <div
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="h-[28rem] overflow-y-auto rounded-b-xl bg-term p-4 font-mono text-xs leading-5 whitespace-pre-wrap break-all text-[#c9ccd6]"
      >
        {lines.map((l, i) => <div key={i} className={cx(lineClass(l))}>{l}</div>)}
        {running && <div className="text-faint">▌</div>}
      </div>}
    </Card>
  );
}

/** A thin progress bar with a line of details under it. */
export function ProgressBar({ value, failed, children }: { value: number; failed?: boolean; children?: ReactNode }) {
  return (
    <div>
      <div className="h-1.5 overflow-hidden rounded-full bg-card-2">
        <div className={cx("h-full rounded-full transition-[width]", failed ? "bg-bad" : "bg-accent")} style={{ width: `${value}%` }} />
      </div>
      {children && <div className="mt-1.5 flex flex-wrap gap-x-4 text-xs text-muted">{children}</div>}
    </div>
  );
}
