import { useEffect, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, KeyRound, PlugZap, RefreshCw, Save, XCircle } from "lucide-react";
import { get, post, put } from "../lib/api";
import { dateTime } from "../lib/format";
import { Badge, Button, Callout, Card, cx, Field, Input, PageHeader, PasswordInput, Select, Spinner, Tabs, useToast } from "../components/ui";
import { PathInput } from "../components/PathPicker";
import { RootFolderForm } from "../components/RootFolder";

interface SettingsSummary {
  settings: {
    root_dir: string;
    host: string;
    port: number;
    session_hours: number;
    world_shutdown_delay: number;
    soap_username: string;
    soap_password_set: boolean;
  };
  configured: boolean;
  error: string | null;
  config: null | {
    world_conf: string;
    auth_conf: string;
    databases: Record<string, { host: string; port: number; user: string; database: string }>;
    realm_id: number;
    world_port: number;
    auth_port: number;
    logs_dir: string;
    data_dir: string;
    soap_enabled: boolean;
    soap_host: string;
    soap_port: number;
    mysqldump: string;
  };
}

interface TestResult {
  name: string;
  ok: boolean;
  detail: string;
}

interface RemoteInfo {
  enabled: boolean;
  port: number;
  tls_cert: string;
  tls_key: string;
  own_cert: boolean;
  cert: { subject: string; self_signed: boolean; names: string[]; expires: number; fingerprint: string } | null;
  cert_error: string | null;
  default_password: boolean;
  active_port: number | null;
  restart_required: boolean;
  urls: string[];
}

// ---- layout -------------------------------------------------------------------------------------------------

/** One settings section: title + explanation on the left, the form card on the right with an action bar. */
function Section({ title, description, badge, footer, children }: {
  title: string;
  description: ReactNode;
  badge?: ReactNode;
  footer?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="grid gap-4 border-b border-line py-8 first:pt-2 last:border-b-0 lg:grid-cols-[16rem_minmax(0,1fr)] lg:gap-10">
      <div>
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold">{title}</h2>
          {badge}
        </div>
        <div className="mt-1.5 text-[13px] leading-relaxed text-muted">{description}</div>
      </div>
      <Card>
        <div className="space-y-4 p-5">{children}</div>
        {footer && (
          <div className="flex flex-wrap items-center justify-end gap-2 rounded-b-xl border-t border-line bg-card-2/50 px-5 py-3">{footer}</div>
        )}
      </Card>
    </section>
  );
}

function Result({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <span className={cx("mr-auto flex min-w-0 items-center gap-1.5 text-xs", ok ? "text-ok" : "text-bad")}>
      {ok ? <CheckCircle2 className="size-3.5 shrink-0" /> : <XCircle className="size-3.5 shrink-0" />}
      <span className="truncate">{children}</span>
    </span>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_minmax(0,1fr)] gap-4 border-b border-line py-2 text-[13px] last:border-b-0">
      <dt className="text-muted">{label}</dt>
      <dd className="truncate font-mono text-xs leading-5">{children}</dd>
    </div>
  );
}

// ---- page ----------------------------------------------------------------------------------------------------

type Tab = "general" | "server" | "security";
const TABS: { key: Tab; label: string }[] = [
  { key: "general", label: "General" },
  { key: "server", label: "Server" },
  { key: "security", label: "Security" },
];

export function Settings() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({ queryKey: ["settings"], queryFn: () => get<SettingsSummary>("/api/settings") });
  const [form, setForm] = useState({ session_hours: 12, world_shutdown_delay: 10 });
  const [saving, setSaving] = useState(false);
  const [tests, setTests] = useState<TestResult[] | null>(null);
  const [testing, setTesting] = useState(false);
  const [tab, setTab] = useState<Tab>("general");

  useEffect(() => {
    if (data) {
      const s = data.settings;
      setForm({ session_hours: s.session_hours, world_shutdown_delay: s.world_shutdown_delay });
    }
  }, [data]);

  if (isLoading || !data) return <Spinner />;

  const save = async () => {
    setSaving(true);
    try {
      await put("/api/settings", form);
      toast({ tone: "ok", title: "Settings saved" });
      qc.invalidateQueries();
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't save", body: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      setTests(await post<TestResult[]>("/api/settings/test"));
    } catch (e) {
      toast({ tone: "bad", title: "Test failed", body: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };

  const cfg = data.config;
  const failed = tests?.filter((t) => !t.ok).length ?? 0;
  return (
    <div className="max-w-6xl">
      <PageHeader title="Settings" subtitle="Where AzerothCore lives and how the panel behaves" />
      {!data.configured && (
        <div className="mb-4">
          <Callout tone="accent">
            {data.settings.root_dir
              ? <>AzerothCore isn't built into this folder yet. Follow the <a className="underline" href="#/setup">Setup</a> page, then build and deploy on Compilation.</>
              : <>Welcome. Choose your AzerothCore folder below (a new or empty one is fine), then follow the <a className="underline" href="#/setup">Setup</a> page.</>}
          </Callout>
        </div>
      )}
      {data.error && <div className="mb-4"><Callout tone="bad">{data.error}</Callout></div>}
      <Tabs value={tab} onChange={setTab} tabs={TABS} />

      {tab === "general" && <div>
      <Section
        title="AzerothCore folder"
        description="Where AzerothCore lives on this PC: its source, build, server and MySQL are kept in this folder."
        footer={
          <>
            {tests && <Result ok={!failed}>{failed ? `${failed} of ${tests.length} checks failed` : `All ${tests.length} checks passed`}</Result>}
            <Button icon={<PlugZap className="size-4" />} loading={testing} onClick={test} disabled={!data.configured}>Test connections</Button>
          </>
        }
      >
        <RootFolderForm />
        {tests && (
          <div className="divide-y divide-line rounded-lg border border-line">
            {tests.map((t) => (
              <div key={t.name} className="flex items-center gap-2 px-3 py-2 text-xs">
                {t.ok ? <CheckCircle2 className="size-3.5 shrink-0 text-ok" /> : <XCircle className="size-3.5 shrink-0 text-bad" />}
                <span className="w-56 shrink-0 font-medium">{t.name}</span>
                <span className="truncate text-muted">{t.detail}</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Detected configuration" description="Read from worldserver.conf and authserver.conf. Change these in Config Files.">
        {cfg ? (
          <dl>
            <Row label="Realm ID">{cfg.realm_id}</Row>
            <Row label="World / auth port">{cfg.world_port} / {cfg.auth_port}</Row>
            {Object.entries(cfg.databases).map(([k, d]) => (
              <Row key={k} label={`${k[0].toUpperCase()}${k.slice(1)} database`}>{d.user}@{d.host}:{d.port}/{d.database}</Row>
            ))}
            <Row label="Logs folder">{cfg.logs_dir}</Row>
            <Row label="Data folder">{cfg.data_dir}</Row>
            <Row label="mysqldump">{cfg.mysqldump || "not found"}</Row>
            <Row label="SOAP">{cfg.soap_enabled ? `enabled (${cfg.soap_host}:${cfg.soap_port})` : "disabled"}</Row>
          </dl>
        ) : (
          <p className="text-[13px] text-muted">Nothing yet: the server isn't built and deployed into the AzerothCore folder.</p>
        )}
      </Section>

      <p className="pt-2 pb-4 text-xs text-faint">
        Panel address <span className="font-mono text-muted">http://{data.settings.host}:{data.settings.port}</span> (this PC only). Panel data is in the
        panel's <span className="font-mono">data</span> folder, backups in <span className="font-mono">backups</span>.
      </p>
      </div>}

      {tab === "server" && <div>
        <Section
          title="Safe stop"
          description="How long players are warned in game before a safe worldserver stop."
          footer={<Button variant="primary" icon={<Save className="size-4" />} loading={saving} onClick={save}>Save</Button>}
        >
          <Field label="World shutdown countdown (seconds)" hint="In-game warning before a safe worldserver stop">
            <Input className="max-w-xs" type="number" min={0} max={3600} value={form.world_shutdown_delay} onChange={(e) => setForm({ ...form, world_shutdown_delay: Number(e.target.value) })} />
          </Field>
        </Section>
        <SoapSection data={data} />
      </div>}

      {tab === "security" && <div>
        <PasswordSection />
        <Section
          title="Sign-in"
          description="How long a sign-in to this panel stays valid."
          footer={<Button variant="primary" icon={<Save className="size-4" />} loading={saving} onClick={save}>Save</Button>}
        >
          <Field label="Session length (hours)" hint="After this you sign in again">
            <Input className="max-w-xs" type="number" min={1} max={720} value={form.session_hours} onChange={(e) => setForm({ ...form, session_hours: Number(e.target.value) })} />
          </Field>
        </Section>
        <RemoteSection />
      </div>}
    </div>
  );
}

// ---- SOAP --------------------------------------------------------------------------------------------------------

/** SOAP account for GM commands (SOAP first, console fallback). The password is write-only. */
function SoapSection({ data }: { data: SettingsSummary }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [username, setUsername] = useState(data.settings.soap_username);
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; message: string } | null>(null);
  const enabled = !!data.config?.soap_enabled;

  const save = async () => {
    setSaving(true);
    try {
      await put("/api/settings/soap", { username, password: password || null });
      setPassword("");
      setResult(null);
      toast({ tone: "ok", title: "SOAP account saved" });
      qc.invalidateQueries();
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't save", body: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const test = async () => {
    setTesting(true);
    try {
      setResult(await post<{ ok: boolean; message: string }>("/api/settings/soap/test"));
    } catch (e) {
      setResult({ ok: false, message: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <Section
      title="SOAP"
      badge={enabled ? <Badge tone="ok" dot>On</Badge> : <Badge tone="muted">Off</Badge>}
      description="GM commands go over SOAP when it's set up: exact replies, and it works for a worldserver started outside the panel. Otherwise they go through the worldserver console."
      footer={
        <>
          {result && <Result ok={result.ok}>{result.message}</Result>}
          <Button icon={<PlugZap className="size-4" />} loading={testing} onClick={test} disabled={!data.configured}>Test SOAP</Button>
          <Button variant="primary" icon={<Save className="size-4" />} loading={saving} onClick={save}>Save</Button>
        </>
      }
    >
      {!enabled && (
        <Callout tone="warn">
          SOAP is off. Set <code className="font-mono">SOAP.Enabled = 1</code> in worldserver.conf (Config Files) and restart the worldserver.
        </Callout>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Account" hint="Game account with GM level 3 (Administrator)">
          <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
        </Field>
        <Field label="Password" hint={data.settings.soap_password_set ? "Saved. Leave empty to keep it." : undefined}>
          <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder={data.settings.soap_password_set ? "••••••••" : ""} autoComplete="new-password" />
        </Field>
      </div>
    </Section>
  );
}

// ---- remote access ------------------------------------------------------------------------------------------------

/** Second listener over HTTPS for other devices. This PC keeps using plain http://127.0.0.1. */
function RemoteSection() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["settings-remote"], queryFn: () => get<RemoteInfo>("/api/settings/remote") });
  const [form, setForm] = useState({ enabled: false, port: 8443, own: false, tls_cert: "", tls_key: "" });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data) setForm({ enabled: data.enabled, port: data.port, own: data.own_cert, tls_cert: data.tls_cert, tls_key: data.tls_key });
  }, [data]);

  if (!data) return null;

  const save = async () => {
    setSaving(true);
    try {
      const r = await put<RemoteInfo>("/api/settings/remote", {
        enabled: form.enabled,
        port: form.port,
        tls_cert: form.own ? form.tls_cert : "",
        tls_key: form.own ? form.tls_key : "",
      });
      qc.setQueryData(["settings-remote"], r);
      toast({ tone: "ok", title: "Remote access saved", body: r.restart_required ? "Restart the panel (stop.bat, then start.bat) to apply." : undefined });
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't save", body: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const regenerate = async () => {
    try {
      qc.setQueryData(["settings-remote"], await post<RemoteInfo>("/api/settings/remote/regenerate"));
      toast({ tone: "ok", title: "New self-signed certificate created", body: "Restart the panel to use it." });
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't regenerate", body: (e as Error).message });
    }
  };

  return (
    <Section
      title="Remote access"
      badge={data.active_port ? <Badge tone="ok" dot>Active · {data.active_port}</Badge> : <Badge tone="muted">Off</Badge>}
      description={
        <>
          <p>Open the panel from other devices over HTTPS. This PC keeps using the local address.</p>
          <p className="mt-2 text-xs text-faint">
            Windows Firewall may ask to allow Python the first time. From outside your network, forward the port on your router, or better, use a VPN such as
            Tailscale. 5 failed sign-ins lock an address for 15 minutes; every action is listed under Logs → Panel Actions.
          </p>
        </>
      }
      footer={
        <>
          {!form.own && !data.own_cert && data.cert && (
            <Button variant="ghost" icon={<RefreshCw className="size-4" />} className="mr-auto" onClick={regenerate}>Regenerate certificate</Button>
          )}
          <Button variant="primary" icon={<Save className="size-4" />} loading={saving} onClick={save}>Save</Button>
        </>
      }
    >
      {data.default_password && <Callout tone="bad">Change the default admin password first (Admin password above).</Callout>}
      {data.restart_required && <Callout tone="warn">Restart the panel (stop.bat, then start.bat) to apply these settings.</Callout>}
      <label className="flex cursor-pointer items-center justify-between gap-4 rounded-lg border border-line px-4 py-3">
        <span>
          <span className="block text-[13px] font-medium">Allow access from other devices</span>
          <span className="block text-xs text-muted">Adds an HTTPS address on this PC's network addresses</span>
        </span>
        <input type="checkbox" checked={form.enabled} onChange={(e) => setForm({ ...form, enabled: e.target.checked })} className="size-4 accent-[var(--accent)]" />
      </label>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="HTTPS port">
          <Input type="number" min={1} max={65535} value={form.port} onChange={(e) => setForm({ ...form, port: Number(e.target.value) })} />
        </Field>
        <Field label="Certificate">
          <Select value={form.own ? "own" : "self"} onChange={(e) => setForm({ ...form, own: e.target.value === "own" })}>
            <option value="self">Self-signed (automatic)</option>
            <option value="own">Own certificate files</option>
          </Select>
        </Field>
      </div>
      {form.own && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Certificate file (.pem / .crt)">
            <PathInput mode="file" ext=".pem,.crt,.cer" value={form.tls_cert} onChange={(v) => setForm({ ...form, tls_cert: v })} placeholder="C:\certs\panel-chain.pem" />
          </Field>
          <Field label="Private key file (.pem / .key)">
            <PathInput mode="file" ext=".pem,.key" value={form.tls_key} onChange={(v) => setForm({ ...form, tls_key: v })} placeholder="C:\certs\panel-key.pem" />
          </Field>
        </div>
      )}
      {data.cert_error && <Callout tone="bad">{data.cert_error}</Callout>}
      {(data.cert || data.urls.length > 0) && (
        <dl className="rounded-lg border border-line px-4 py-1">
          {data.urls.length > 0 && <Row label="Addresses">{data.urls.join("   ")}</Row>}
          {data.cert && (
            <>
              <Row label="Certificate">{data.cert.self_signed ? "Self-signed (browsers warn once)" : data.cert.subject}</Row>
              <Row label="Valid for">{data.cert.names.join(", ") || "—"}</Row>
              <Row label="Expires">{dateTime(data.cert.expires)}</Row>
              <Row label="SHA-256">{data.cert.fingerprint}</Row>
            </>
          )}
        </dl>
      )}
    </Section>
  );
}

// ---- admin password -------------------------------------------------------------------------------------------

function PasswordSection() {
  const qc = useQueryClient();
  const toast = useToast();
  const [pw, setPw] = useState({ current: "", next: "" });
  const [busy, setBusy] = useState(false);

  const change = async () => {
    setBusy(true);
    try {
      await post("/api/auth/password", { current: pw.current, new: pw.next });
      setPw({ current: "", next: "" });
      toast({ tone: "ok", title: "Password changed", body: "Other browsers and devices were signed out." });
      qc.invalidateQueries({ queryKey: ["settings-remote"] });
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't change password", body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      title="Admin password"
      description="The password for signing in to this panel. Changing it signs out every other browser and device."
      footer={<Button variant="primary" icon={<KeyRound className="size-4" />} loading={busy} onClick={change} disabled={!pw.current || pw.next.length < 8}>Change password</Button>}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Current password">
          <PasswordInput value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} autoComplete="current-password" />
        </Field>
        <Field label="New password" hint="At least 8 characters">
          <PasswordInput value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} autoComplete="new-password" />
        </Field>
      </div>
    </Section>
  );
}
