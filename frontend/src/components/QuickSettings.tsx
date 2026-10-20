import { useEffect, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Info, RotateCcw, Save } from "lucide-react";
import { get, put } from "../lib/api";
import { Button, Card, Callout, cx, Input, Select, Spinner, useToast } from "./ui";

interface Setting {
  key: string;
  label: string;
  kind: "toggle" | "select" | "int" | "rate";
  value: string;
  default: string | null;
  description: string;
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
}
interface QuickState {
  found: boolean;
  file: string;
  groups: { title: string; items: Setting[] }[];
  world_running: boolean;
}

function Toggle({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={() => onChange(!on)}
      className={cx("relative h-5 w-9 shrink-0 rounded-full transition-colors", on ? "bg-accent" : "bg-line-strong")}
    >
      <span className={cx("absolute top-0.5 size-4 rounded-full bg-white shadow transition-all", on ? "left-[18px]" : "left-0.5")} />
    </button>
  );
}

/** The control fills its grid cell; every kind has the same height so a row of fields lines up. */
function Control({ s, value, onChange }: { s: Setting; value: string; onChange: (v: string) => void }) {
  if (s.kind === "toggle") {
    const on = value === "1";
    return (
      <div className="flex h-9 items-center justify-between rounded-md border border-line bg-card-2 px-3">
        <span className={cx("text-xs", on ? "font-medium text-accent-text" : "text-muted")}>{on ? "On" : "Off"}</span>
        <Toggle on={on} onChange={(v) => onChange(v ? "1" : "0")} />
      </div>
    );
  }
  if (s.kind === "select") {
    const known = s.options?.some((o) => o.value === value);
    return (
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        {!known && <option value={value}>{value} (current)</option>}
        {s.options?.map((o) => <option key={o.value} value={o.value}>{o.label} ({o.value})</option>)}
      </Select>
    );
  }
  return (
    <div className="relative">
      <Input
        className={cx("font-mono", s.kind === "rate" && "pr-7")}
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value.replace(",", "."))}
      />
      {s.kind === "rate" && <span className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 text-xs text-faint">×</span>}
    </div>
  );
}

/** Config Files -> Quick settings: common worldserver.conf values as a form. */
export function QuickSettings({ onSaved }: { onSaved: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, error } = useQuery({ queryKey: ["quick-settings"], queryFn: () => get<QuickState>("/api/quick-settings"), retry: false });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const current = useMemo(
    () => Object.fromEntries((data?.groups ?? []).flatMap((g) => g.items.map((s) => [s.key, s.value]))),
    [data],
  );
  useEffect(() => setDraft(current), [current]);

  if (error) return <Callout tone="bad">{(error as Error).message}</Callout>;
  if (!data) return <Spinner />;
  if (!data.found) return <Callout tone="accent">There's no worldserver.conf yet. Deploy on Compilation creates it.</Callout>;

  const changed = Object.keys(draft).filter((k) => draft[k] !== current[k]);
  const save = async () => {
    setSaving(true);
    try {
      const r = await put<QuickState & { changed: string[] }>("/api/quick-settings", { values: Object.fromEntries(changed.map((k) => [k, draft[k]])) });
      qc.setQueryData(["quick-settings"], r);
      toast({ tone: "ok", title: `Saved ${r.changed.length} setting${r.changed.length === 1 ? "" : "s"}`, body: r.world_running ? "Restart the worldserver to apply them." : undefined });
      onSaved();
    } catch (e) {
      toast({ tone: "bad", title: "Couldn't save", body: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  // Groups with few settings take half the width and sit side by side (grid-flow-dense fills the gaps);
  // the others take the whole row. Inside a card the settings flow in columns, name above the control.
  const half = (g: QuickState["groups"][number]) => g.items.length <= 4;
  // A full-width card with up to 6 settings shows them in one row (Item drops: 5); longer ones use 4 columns.
  const COLS: Record<number, string> = { 4: "xl:grid-cols-4", 5: "xl:grid-cols-5", 6: "xl:grid-cols-6" };
  const cols = (g: QuickState["groups"][number]) => COLS[g.items.length <= 6 ? g.items.length : 4];
  const group = (g: QuickState["groups"][number]) => (
    <Card key={g.title} className={cx(!half(g) && "lg:col-span-2")}>
      <div className="border-b border-line px-4 py-2.5 text-[13px] font-semibold">{g.title}</div>
      <div className={cx("grid gap-x-4 gap-y-3 p-4 sm:grid-cols-2", !half(g) && cols(g))}>
        {g.items.map((s) => {
          const value = draft[s.key] ?? s.value;
          const edited = value !== s.value;
          const offDefault = s.default != null && value !== s.default;
          const tip = [s.description, `${s.key}${s.default != null ? ` · default ${s.default}` : ""}`].filter(Boolean).join("\n\n");
          return (
            <div key={s.key} className="min-w-0">
              <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-muted">
                <span className={cx("truncate", edited && "text-accent-text")}>{s.label}</span>
                <span title={tip} className="shrink-0 text-faint hover:text-muted"><Info className="size-3.5" /></span>
                {offDefault && (
                  <button className="ml-auto shrink-0 text-faint hover:text-text" title={`Back to the default (${s.default})`}
                    onClick={() => setDraft({ ...draft, [s.key]: s.default! })}>
                    <RotateCcw className="size-3.5" />
                  </button>
                )}
              </div>
              <Control s={s} value={value} onChange={(v) => setDraft({ ...draft, [s.key]: v })} />
            </div>
          );
        })}
      </div>
    </Card>
  );

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-end gap-2">
        <span className={cx("mr-auto text-xs", changed.length ? "text-accent-text" : "text-muted")}>
          {changed.length
            ? `${changed.length} unsaved change${changed.length === 1 ? "" : "s"}`
            : "Changes go into worldserver.conf. Restart the worldserver to apply them."}
        </span>
        <Button size="sm" variant="ghost" disabled={!changed.length} onClick={() => setDraft(current)}>Revert</Button>
        <Button size="sm" variant="primary" icon={<Save className="size-3.5" />} loading={saving} disabled={!changed.length} onClick={save}>Save</Button>
      </div>
      <div className="grid grid-flow-dense items-start gap-4 lg:grid-cols-2">{data.groups.map(group)}</div>
    </div>
  );
}
