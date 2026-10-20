import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileCog, Package, RefreshCw, Save } from "lucide-react";
import { get, put } from "../lib/api";
import { CodeEditor, DiffView } from "../components/CodeEditor";
import { ConfigValues } from "../components/ConfigValues";
import { QuickSettings } from "../components/QuickSettings";
import { Badge, Button, Callout, Card, cx, Empty, Modal, PageHeader, Spinner, Tabs, useConfirm, useToast } from "../components/ui";

interface ConfigEntry {
  id: string;
  group: "core" | "modules";
  service: "world" | "auth";
  restart_required: boolean;
}
interface ConfigFile {
  id: string;
  content: string;
  hash: string;
  service: "world" | "auth";
  restart_required: boolean;
}

const normalize = (s: string) => s.replace(/\r\n/g, "\n");

type Tab = "setup" | "quick" | "editor";
const TABS: { key: Tab; label: string }[] = [
  { key: "setup", label: "Setup" },
  { key: "quick", label: "Quick settings" },
  { key: "editor", label: "Editor" },
];

export function Configs() {
  const qc = useQueryClient();
  const toast = useToast();
  const confirm = useConfirm();
  const { data: files, isLoading, error } = useQuery({ queryKey: ["configs"], queryFn: () => get<ConfigEntry[]>("/api/configs"), retry: false });
  const [selected, setSelected] = useState<string | null>(null);
  const [file, setFile] = useState<ConfigFile | null>(null);
  const [draft, setDraft] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<Tab>("setup");
  const dirty = !!file && normalize(draft) !== normalize(file.content);

  const load = async (id: string) => {
    const f = await get<ConfigFile>(`/api/configs/${id}`);
    setFile(f);
    setDraft(normalize(f.content));
    setSelected(id);
  };

  useEffect(() => {
    if (!selected && files?.length) load(files[0].id);
  }, [files, selected]);

  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => dirty && e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const select = async (id: string) => {
    if (dirty && !(await confirm({ title: "Discard changes?", body: `Your unsaved changes to ${selected} will be lost.`, confirm: "Discard", danger: true }))) return;
    load(id);
  };

  const save = async () => {
    if (!file) return;
    setSaving(true);
    try {
      const r = await put<{ hash: string; restart_required: boolean }>(`/api/configs/${file.id}`, { content: draft, base_hash: file.hash });
      setFile({ ...file, content: draft, hash: r.hash, restart_required: r.restart_required });
      setReviewing(false);
      toast({ tone: "ok", title: `${file.id} saved` });
      qc.invalidateQueries({ queryKey: ["configs"] });
    } catch (e) {
      toast({ tone: "bad", title: "Save failed", body: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  // The Setup or Quick settings tab rewrote files: show the open one's new content unless it has edits.
  const applied = () => {
    qc.invalidateQueries({ queryKey: ["configs"] });
    qc.invalidateQueries({ queryKey: ["quick-settings"] });
    qc.invalidateQueries({ queryKey: ["config-values"] });
    if (selected && !dirty) load(selected);
  };
  const header = (
    <>
      <PageHeader title="Config Files" subtitle="worldserver, authserver and module configs" />
      <Tabs value={tab} onChange={setTab} tabs={TABS.map((t) => ({ ...t, dot: t.key === "editor" && dirty }))} />
    </>
  );

  if (tab === "setup") return <>{header}<ConfigValues onApplied={applied} /></>;
  if (tab === "quick") return <>{header}<QuickSettings onSaved={applied} /></>;
  if (isLoading) return <>{header}<Spinner /></>;
  if (!files?.length) {
    return (
      <>
        {header}
        <Empty icon={<FileCog className="size-6" />} title="No config files yet">
          {error ? (error as Error).message : "Deploy on Compilation creates them."}
        </Empty>
      </>
    );
  }
  const groups: { title: string; items: ConfigEntry[] }[] = [
    { title: "Core", items: files.filter((f) => f.group === "core") },
    { title: "Modules", items: files.filter((f) => f.group === "modules") },
  ];
  const restartTarget = file?.service === "auth" ? "Authserver" : "Worldserver";

  return (
    <div className="flex flex-col">
      {header}
      <div className="grid h-[calc(100vh-11rem)] min-h-[480px] gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card className="overflow-y-auto p-2">
          <div className="flex items-center justify-between px-2 py-1.5">
            <span className="flex items-center gap-2 text-[13px] font-semibold"><FileCog className="size-4 text-accent" /> Config files</span>
            <button className="text-muted hover:text-text" onClick={() => qc.invalidateQueries({ queryKey: ["configs"] })} title="Refresh">
              <RefreshCw className="size-3.5" />
            </button>
          </div>
          {groups.map((g) =>
            g.items.length ? (
              <div key={g.title} className="mt-2">
                <div className="label-caps px-2 pb-1 !text-[10.5px] !text-faint">{g.title}</div>
                {g.items.map((f) => (
                  <button
                    key={f.id}
                    onClick={() => select(f.id)}
                    className={cx("flex w-full items-center gap-2 rounded-lg px-2.5 py-2 text-left font-mono text-xs", selected === f.id ? "bg-accent-soft text-accent-text" : "text-muted hover:bg-card-2 hover:text-text")}
                  >
                    {g.title === "Modules" ? <Package className="size-3.5 shrink-0" /> : <FileCog className="size-3.5 shrink-0" />}
                    <span className="truncate">{f.id.replace("modules/", "")}</span>
                    {f.restart_required && <span className="ml-auto size-1.5 shrink-0 rounded-full bg-warn" title="Restart required" />}
                  </button>
                ))}
              </div>
            ) : null,
          )}
        </Card>

        <Card className="flex min-h-[480px] flex-col overflow-hidden">
          <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate font-mono text-[13px]">{file?.id}</span>
              {dirty && <Badge tone="warn">Unsaved</Badge>}
              {file?.restart_required && !dirty && <Badge tone="warn">Restart {restartTarget} to apply</Badge>}
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs text-faint">Ctrl+S to save</span>
              <Button size="sm" variant="ghost" disabled={!dirty} onClick={() => file && setDraft(normalize(file.content))}>
                Revert
              </Button>
              <Button size="sm" variant="primary" icon={<Save className="size-3.5" />} disabled={!dirty} onClick={() => setReviewing(true)}>
                Save
              </Button>
            </div>
          </div>
          {file?.restart_required && (
            <div className="border-b border-line p-3">
              <Callout tone="warn">This file changed after {restartTarget} started. Restart it from Server Control for the change to take effect.</Callout>
            </div>
          )}
          <div className="min-h-0 flex-1">{file && <CodeEditor key={file.id} lang="conf" value={draft} onChange={setDraft} onSave={() => dirty && setReviewing(true)} />}</div>
        </Card>
      </div>

      <Modal
        open={reviewing && !!file}
        wide
        title={`Review changes to ${file?.id}`}
        onClose={() => setReviewing(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setReviewing(false)}>Keep editing</Button>
            <Button variant="primary" icon={<Save className="size-3.5" />} loading={saving} onClick={save}>
              Save file
            </Button>
          </>
        }
      >
        <p className="text-xs text-muted">Left: file on disk. Right: your version.</p>
        {file && reviewing && <DiffView original={normalize(file.content)} modified={draft} />}
      </Modal>
    </div>
  );
}
