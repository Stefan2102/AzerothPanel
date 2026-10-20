import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AppWindow, ArrowDown, ArrowUp, Play, Plus, Save, Trash2 } from "lucide-react";
import { put, type Shortcut, type ShortcutsState } from "../lib/api";
import { useLaunchShortcut, useShortcuts } from "../lib/hooks";
import { PathInput } from "../components/PathPicker";
import { Button, Card, CardHeader, Empty, Field, Input, PageHeader, Spinner, useToast } from "../components/ui";

type Row = Omit<Shortcut, "id"> & { id?: string };

const BLANK: Row = { name: "", path: "", args: "" };
const EXT = ".exe,.bat,.cmd,.lnk";

export function Shortcuts() {
  const { data } = useShortcuts();
  const qc = useQueryClient();
  const toast = useToast();
  const launch = useLaunchShortcut();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (data && rows === null) setRows(data.items);
  }, [data, rows]);

  if (!data || !rows) return <Spinner />;
  const dirty = JSON.stringify(rows) !== JSON.stringify(data.items);
  const shown = new Set(rows.map((r) => r.name.toLowerCase()));
  const suggestions = data.suggestions.filter((s) => !shown.has(s.name.toLowerCase()));

  const update = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  /** Sidebar order is the list order. */
  const move = (i: number, by: -1 | 1) => {
    const next = [...rows];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    setRows(next);
  };

  const save = async () => {
    setSaving(true);
    try {
      const r = await put<ShortcutsState>("/api/shortcuts", { items: rows });
      qc.setQueryData(["shortcuts"], r);
      setRows(r.items);
      toast({ tone: "ok", title: "Shortcuts saved" });
    } catch (e) {
      toast({ tone: "bad", title: "Could not save", body: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <PageHeader
        title="Shortcuts"
        subtitle="Programs you start from the sidebar, e.g. the game client or Ollama."
        right={
          <Button variant="primary" icon={<Save className="size-4" />} loading={saving} disabled={!dirty} onClick={save}>
            Save
          </Button>
        }
      />
      <Card>
        <CardHeader
          title="Your shortcuts"
          subtitle="They start like a double-click; the panel doesn't stop them."
          right={
            <div className="flex flex-wrap justify-end gap-2">
              {suggestions.map((s) => (
                <Button key={s.name} size="sm" icon={<Plus className="size-3.5" />} onClick={() => setRows([...rows, { ...s }])}>
                  {s.name}
                </Button>
              ))}
              <Button size="sm" icon={<Plus className="size-3.5" />} onClick={() => setRows([...rows, { ...BLANK }])}>
                Add
              </Button>
            </div>
          }
        />
        {rows.length === 0 ? (
          <Empty icon={<AppWindow className="size-6" />} title="No shortcuts yet" />
        ) : (
          <div className="divide-y divide-line">
            {rows.map((r, i) => {
              const saved = data.items.find((s) => s.id === r.id);
              const unchanged = saved && JSON.stringify(saved) === JSON.stringify(r);
              return (
                <div key={r.id ?? `new-${i}`} className="grid gap-3 p-4 lg:grid-cols-[minmax(0,12rem)_minmax(0,2fr)_minmax(0,1fr)_auto]">
                  <Field label="Name">
                    <Input value={r.name} maxLength={40} onChange={(e) => update(i, { name: e.target.value })} placeholder="World of Warcraft" />
                  </Field>
                  <Field label="File">
                    <PathInput mode="file" ext={EXT} title="Choose the program" value={r.path} onChange={(path) => update(i, { path })} placeholder="D:\Games\WoW\Wow.exe" />
                  </Field>
                  <Field label="Arguments (optional)">
                    <Input className="font-mono" value={r.args} maxLength={300} onChange={(e) => update(i, { args: e.target.value })} placeholder="None" />
                  </Field>
                  <div className="flex items-start gap-2 lg:pt-6">
                    <Button size="sm" icon={<Play className="size-3.5" />} disabled={!unchanged} title={unchanged ? undefined : "Save first"} onClick={() => saved && launch(saved)}>
                      Start
                    </Button>
                    <Button size="sm" variant="ghost" icon={<ArrowUp className="size-3.5" />} aria-label="Move up" title="Move up" disabled={i === 0} onClick={() => move(i, -1)} />
                    <Button size="sm" variant="ghost" icon={<ArrowDown className="size-3.5" />} aria-label="Move down" title="Move down" disabled={i === rows.length - 1} onClick={() => move(i, 1)} />
                    <Button size="sm" variant="ghost" className="!text-bad" icon={<Trash2 className="size-3.5" />} aria-label="Remove" onClick={() => setRows(rows.filter((_, j) => j !== i))} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </>
  );
}
