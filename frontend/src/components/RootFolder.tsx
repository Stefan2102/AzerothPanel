import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { get, put } from "../lib/api";
import { Button, Field, Spinner, useToast } from "./ui";
import { PathInput } from "./PathPicker";

export interface RootSummary {
  settings: { root_dir: string };
  /** Each fixed place relative to the AzerothCore folder ("install/server"). */
  layout: Record<"source" | "build" | "server", string>;
  /** The same places as full paths; empty until the folder is chosen. */
  paths: Partial<Record<"source" | "build" | "server", string>>;
}

const PARTS: { key: keyof RootSummary["paths"]; label: string; what: string }[] = [
  { key: "source", label: "Source", what: "AzerothCore code (cloned on Setup)" },
  { key: "build", label: "Build", what: "Compiler output" },
  { key: "server", label: "Server", what: "worldserver, authserver, configs, data, logs" },];

/** The one folder the user chooses; everything else has a fixed place inside it. */
export function RootFolderForm() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: () => get<RootSummary>("/api/settings") });
  const [root, setRoot] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data && root === null) setRoot(data.settings.root_dir);
  }, [data, root]);

  if (!data) return <Spinner />;
  const value = root ?? "";
  const changed = value.trim() !== data.settings.root_dir;

  const save = async () => {
    setSaving(true);
    try {
      const r = await put<RootSummary>("/api/settings/root", { root_dir: value.trim() });
      setRoot(r.settings.root_dir);
      toast({ tone: "ok", title: "AzerothCore folder saved" });
      qc.invalidateQueries();
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't save", body: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  // Saved: the server's paths. While typing: where they would be with the new folder.
  const preview = (key: keyof RootSummary["paths"]) => {
    if (!changed) return data.paths[key] ?? "—";
    const base = value.trim().replace(/[\\/]+$/, "");
    return base ? `${base}\\${data.layout[key].replace(/\//g, "\\")}` : "—";
  };

  return (
    <div className="space-y-4">
      <Field label="AzerothCore folder" hint="A new, empty or existing folder.">
        <div className="flex gap-2">
          <div className="flex-1"><PathInput value={value} onChange={setRoot} placeholder="D:\AzerothCore" title="Choose the AzerothCore folder (New folder creates one)" /></div>
          <Button variant="primary" icon={<Save className="size-4" />} loading={saving} disabled={!value.trim() || !changed} onClick={save}>Save</Button>
        </div>
      </Field>
      <div className="divide-y divide-line rounded-lg border border-line">
        {PARTS.map((p) => (
          <div key={p.key} className="grid grid-cols-[5rem_minmax(0,1fr)] gap-3 px-3 py-2 text-xs">
            <span className="text-muted">{p.label}</span>
            <span className="min-w-0">
              <span className="block truncate font-mono" title={preview(p.key)}>{preview(p.key)}</span>
              <span className="block truncate text-faint">{p.what}</span>
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
