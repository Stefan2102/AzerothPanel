import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileUp } from "lucide-react";
import { post } from "../lib/api";
import { useStatus } from "../lib/hooks";
import { JobOutput, ProgressBar, type JobBase } from "./JobOutput";
import { Button, Callout, Field, Modal, Select, useToast } from "./ui";
import { PathInput } from "./PathPicker";

interface ImportJob extends JobBase {
  database: string;
  file: string;
  backup: boolean;
  force: boolean;
  detail?: string | null;
  errors?: number;
  first_errors?: string[];
  backup_file?: string | null;
}

const STEPS: Record<string, string> = { backup: "Backup", import: "Import" };
const FILE_NAME = (path: string) => path.split(/[\\/]/).pop() ?? path;

/** Database page: the Import SQL button (with its dialog) and the running or just finished import with its log,
 * returned separately so the page can place them (button in the header, output below it). */
export function useSqlImport(databases: { key: string; database: string }[]) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data: status } = useStatus();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ database: "world", file: "", backup: false, force: false });
  const [starting, setStarting] = useState(false);
  const [job, setJob] = useState<number | null>(null);

  // Follow an import that is still running from before a reload (kept after it ends, to show the result).
  const runningId = status?.sqlimport?.id;
  useEffect(() => {
    if (runningId != null) setJob(runningId);
  }, [runningId]);

  const busy = !!status?.sqlimport;
  const worldUp = status?.services.world.state === "running" || status?.services.world.state === "external";
  const cached = worldUp && (form.database === "world" || form.database === "characters");

  const start = async () => {
    setStarting(true);
    try {
      const r = await post<{ job_id: number }>("/api/sql-import/run", form);
      setJob(r.job_id);
      setOpen(false);
      qc.invalidateQueries({ queryKey: ["status"] });
    } catch (e) {
      toast({ tone: "bad", title: "Import didn't start", body: (e as Error).message });
    } finally {
      setStarting(false);
    }
  };

  const button = (
    <>
      <Button size="sm" icon={<FileUp className="size-3.5" />} disabled={busy} onClick={() => setOpen(true)}
        title={busy ? "An import is running" : "Run an .sql file against one database"}>
        Import SQL
      </Button>

      <Modal
        open={open}
        title="Import SQL file"
        onClose={() => setOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="primary" icon={<FileUp className="size-4" />} loading={starting} disabled={!form.file.trim()} onClick={start}>
              Import
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Database">
            <Select value={form.database} onChange={(e) => setForm({ ...form, database: e.target.value })}>
              {databases.map((d) => <option key={d.key} value={d.key}>{d.key[0].toUpperCase() + d.key.slice(1)} ({d.database})</option>)}
            </Select>
          </Field>
          <Field label="SQL file" hint="Run with MySQL's own client, like on the command line">
            <PathInput mode="file" ext=".sql" value={form.file} onChange={(v) => setForm({ ...form, file: v })} placeholder="D:\SQL\my_changes.sql" title="Choose the .sql file" />
          </Field>
          <label className="flex cursor-pointer items-start gap-2.5">
            <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={form.backup} onChange={(e) => setForm({ ...form, backup: e.target.checked })} />
            <span>
              <span className="block text-[13px]">Back up this database first</span>
              <span className="block text-xs text-faint">Saved in the panel's backups folder; import that file to undo.</span>
            </span>
          </label>
          <label className="flex cursor-pointer items-start gap-2.5">
            <input type="checkbox" className="mt-0.5 size-4 accent-[var(--accent)]" checked={form.force} onChange={(e) => setForm({ ...form, force: e.target.checked })} />
            <span>
              <span className="block text-[13px]">Continue after errors</span>
              <span className="block text-xs text-faint">Otherwise the import stops at the first error (what ran before it stays).</span>
            </span>
          </label>
          {cached && (
            <Callout tone="warn">Worldserver is running. It keeps much of this data in memory, so changes may not show, or be overwritten, until you restart it.</Callout>
          )}
        </div>
      </Modal>
    </>
  );
  const output = job != null && (
        <div className="mb-4">
          <JobOutput<ImportJob>
            key={job}
            base="/api/sql-import"
            jobId={job}
            steps={(j) => (j.backup ? ["backup", "import"] : ["import"])}
            stepLabels={STEPS}
            subtitle={(j) => `Import ${FILE_NAME(j.file)} into ${j.database}`}
            progress={(j) => (j.status === "running" ? <ProgressBar value={j.progress}>{j.detail ? <span>{j.detail}</span> : null}</ProgressBar> : null)}
            summary={(j) => (j.errors
              ? {
                  tone: "warn",
                  text: (
                    <>
                      Imported into {j.database} with {j.errors} error(s) skipped
                      {j.errors > (j.first_errors?.length ?? 0) ? " (all of them are in the log)" : ""}:
                      {j.first_errors?.map((e, i) => <span key={i} className="mt-1 block font-mono text-xs break-all">{e}</span>)}
                    </>
                  ),
                }
              : { tone: "ok", text: `Imported into ${j.database}.${j.backup_file ? ` Backup: ${j.backup_file}` : ""}` })}
            invalidate={[["tables"]]}
            console={false}
          />
        </div>
  );
  return { button, output };
}
