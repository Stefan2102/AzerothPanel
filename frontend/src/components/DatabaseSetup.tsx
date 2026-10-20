import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Database, ShieldAlert } from "lucide-react";
import { get, post } from "../lib/api";
import { useStatus } from "../lib/hooks";
import { JobOutput, ProgressBar, type JobBase } from "./JobOutput";
import { Badge, Button, Callout, Card, CardHeader, Field, Input, PasswordInput, Spinner, useToast } from "./ui";

interface SetupStatus {
  mysql_dir: string;
  found: boolean;
  version: string | null;
  my_ini: boolean;
  port: number | null;
  host: string | null;
  initialised: boolean;
  databases: { name: string; reason: string }[];
  busy: boolean;
}

interface SetupJob extends JobBase {
  databases: string[];
}

const STEPS: Record<string, string> = {
  my_ini: "my.ini", initialize: "Initialise", start: "Start", account: "Account & databases", stop: "Stop",
};

/** Setup -> Database setup: initialise a portable MySQL, create the account and the databases. */
export function DatabaseSetup() {
  const toast = useToast();
  const { data: status } = useStatus();
  const [form, setForm] = useState({ host: "127.0.0.1", port: 3306, user: "", password: "" });
  const loopback = ["127.0.0.1", "localhost"].includes(form.host.trim());
  // The running job and the plan it was started with (the status changes once the job has run).
  const [job, setJob] = useState<{ id: number; add: boolean; steps: string[] } | null>(null);
  const [starting, setStarting] = useState(false);
  // The MySQL folder chosen on Setup -> Requirements. Checked again when you come back to the window
  // (e.g. after extracting the ZIP in Explorer).
  const { data: s } = useQuery({
    queryKey: ["db-setup"],
    queryFn: () => get<SetupStatus>("/api/db-setup"),
    refetchOnWindowFocus: true,
  });

  // IP and port start from an existing my.ini (a fresh setup rewrites it with the fields' values); a refetch
  // (e.g. on window focus) must not overwrite what you typed.
  const [addressEdited, setAddressEdited] = useState(false);
  useEffect(() => {
    if (addressEdited) return;
    if (s?.port) setForm((f) => ({ ...f, port: s.port ?? f.port }));
    if (s?.my_ini) setForm((f) => ({ ...f, host: s.host && s.host !== "0.0.0.0" && s.host !== "*" ? s.host : "127.0.0.1" }));
  }, [s, addressEdited]);

  if (!s) return <Card className="p-5"><Spinner /></Card>;

  const mysqlRunning = status?.services.mysql.state === "running" || status?.services.mysql.state === "external";
  // Why the button is disabled, first reason only (null: it can run).
  const blocked = !s.mysql_dir ? "Choose the MySQL folder under Requirements first."
    : !s.found ? "Choose the MySQL folder under Requirements again."
    : s.busy ? "A database setup is already running."
    : !s.databases.length ? "No databases to create yet: clone the source first."
    : s.initialised ? null
    : mysqlRunning ? "Stop MySQL on Server Control first."
    : !form.host.trim() ? "Enter an IP address."
    : !form.user.trim() && !form.password ? "Enter an account name and password."
    : !form.user.trim() ? "Enter an account name."
    : !form.password ? "Enter a password."
    : null;
  const start = async () => {
    setStarting(true);
    try {
      const r = await post<{ job_id: number }>("/api/db-setup/run", form);
      const steps = s.initialised
        ? ["start", "account", "stop"]
        : ["my_ini", "initialize", "start", "account", "stop"];
      setJob({ id: r.job_id, add: s.initialised, steps });
    } catch (e) {
      toast({ tone: "bad", title: "Database setup didn't start", body: (e as Error).message });
    } finally {
      setStarting(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Database setup"
        subtitle="Prepares a portable MySQL for AzerothCore: my.ini, first start, the account and the databases. AzerothCore creates the tables itself on the first server start."
        right={s.initialised ? <Badge tone="ok" dot>Set up</Badge> : s.found ? <Badge tone="warn" dot>Not set up</Badge> : null}
      />
      <div className="space-y-4 p-4">
        {!s.found && (
          <Callout tone="bad">
            {s.mysql_dir
              ? `No MySQL in ${s.mysql_dir} any more. Choose the MySQL folder under Requirements again.`
              : "Extract the MySQL ZIP anywhere, then choose its folder under Requirements (MySQL → Change)."}
          </Callout>
        )}
        {s.found && (
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-muted">
            <span>Folder <span className="font-mono text-text">{s.mysql_dir}</span></span>
            <span>MySQL <span className="text-text">{s.version ?? "?"}</span></span>
            <span>my.ini: <span className="text-text">{s.my_ini ? `present (port ${s.port ?? "?"})${s.initialised ? "" : ", rewritten by setup"}` : "will be written"}</span></span>
            <span>Data folder: <span className="text-text">{s.initialised ? "initialised" : "empty"}</span></span>
          </div>
        )}

        {s.found && !s.initialised && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Field label="IP address" hint={loopback ? "This PC only (recommended)" : "MySQL listens on this address"}>
                <Input className="font-mono" value={form.host} placeholder="127.0.0.1"
                  onChange={(e) => { setAddressEdited(true); setForm({ ...form, host: e.target.value }); }} />
              </Field>
              <Field label="Port" hint={s.my_ini ? "my.ini is rewritten with this port" : "Written into my.ini"}>
                <Input type="number" min={1} max={65535} value={form.port}
                  onChange={(e) => { setAddressEdited(true); setForm({ ...form, port: Number(e.target.value) }); }} />
              </Field>
              <Field label="Account name" hint="Letters, digits and _">
                <Input value={form.user} onChange={(e) => setForm({ ...form, user: e.target.value })} autoComplete="off" />
              </Field>
              <Field label="Password">
                <PasswordInput value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" />
              </Field>
            </div>
            <p className="text-xs text-muted">
              The connection is remembered. The server configs are not changed here: after setup (and after deploy), put it into them on{" "}
              <a className="underline" href="#/configs">Config Files</a> → Paths for this setup → Save &amp; apply.
            </p>
            <Callout tone="warn">
              <span className="flex items-start gap-1.5">
                <ShieldAlert className="mt-0.5 size-4 shrink-0" />
                <span>
                  This account gets every right on this MySQL (*.* with grant option), and root is removed completely once the account has been checked.
                  {loopback
                    ? " MySQL only listens on 127.0.0.1, so only this PC can reach it."
                    : ` MySQL will listen on ${form.host} and the account may log in from any address, so other machines on that network can reach it: use a strong password.`}
                </span>
              </span>
            </Callout>
          </>
        )}
        {s.initialised && (
          <Callout tone="accent">
            This MySQL is already set up. Missing databases (for example after installing mod-playerbots) can be added; existing ones and the accounts are not touched.
          </Callout>
        )}

        {s.databases.length > 0 && (
          <div>
            <div className="mb-1.5 text-xs font-medium text-muted">Databases</div>
            <div className="divide-y divide-line rounded-lg border border-line">
              {s.databases.map((d) => (
                <div key={d.name} className="flex items-center gap-2 px-3 py-2 text-xs">
                  <Database className="size-3.5 text-muted" />
                  <span className="font-mono">{d.name}</span>
                  <span className="text-faint">{d.reason}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" icon={<CheckCircle2 className="size-4" />} loading={starting}
            disabled={!!blocked}
            onClick={start}>
            {s.initialised ? "Add missing databases" : "Set up database"}
          </Button>
          {blocked && !job && <span className="text-xs text-muted">{blocked}</span>}
        </div>

        {job && (
          <JobOutput<SetupJob>
            key={job.id}
            base="/api/db-setup"
            jobId={job.id}
            steps={() => job.steps}
            stepLabels={STEPS}
            subtitle={() => (job.add ? "Add missing databases" : "Database setup")}
            progress={(j) => (j.status === "running" ? <ProgressBar value={j.progress} /> : null)}
            summary={() => ({
              tone: "ok",
              text: job.add
                ? "Done. Start MySQL on Server Control; the servers create the tables on their first start."
                : "Database ready. Next: Config Files → Paths for this setup → Save & apply puts this account into the server configs. The servers create the tables on their first start.",
            })}
            invalidate={[["db-setup"], ["settings"], ["config-values"]]}
          />
        )}
      </div>
    </Card>
  );
}
