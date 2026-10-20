import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { RotateCcw } from "lucide-react";
import { put } from "../lib/api";
import { ORIGIN_LABEL, type ToolItem } from "../lib/build";
import { Badge, Button, Callout, cx, Field, Modal, useToast } from "./ui";
import { PathInput } from "./PathPicker";

export function StatusChip({ item }: { item: ToolItem }) {
  if (item.status === "ok") {
    return item.advice.some((a) => a.tone === "warn") ? <Badge tone="warn" dot>Advice</Badge> : <Badge tone="ok" dot>OK</Badge>;
  }
  if (item.status === "too_old") return <Badge tone="bad" dot>Too old</Badge>;
  if (item.status === "missing") return <Badge tone="bad" dot>Missing</Badge>;
  if (item.status === "unknown") return <Badge tone="warn" dot>Unknown version</Badge>;
  return <Badge tone="bad" dot>Needs attention</Badge>;
}

export function OriginTag({ origin }: { origin: string | null }) {
  if (!origin) return null;
  return <span className={cx("shrink-0 whitespace-nowrap text-[11px]", origin === "override" ? "text-accent-text" : "text-faint")}>{ORIGIN_LABEL[origin] ?? origin}</span>;
}

/** Change or reset a path override (saved until "Reset to detected"). Without `detected` (MySQL) there is
 * nothing to reset to: the chosen path is the only source. */
export function PathModal({
  itemKey, title, kind, current, origin, candidates, detected = true, hint, onClose,
}: {
  itemKey: string;
  title: string;
  kind: "folder" | "file" | "instance";
  current: string | null;
  origin: string | null;
  candidates: { path: string; version?: string | null }[];
  detected?: boolean;
  hint?: string;
  onClose: () => void;
}) {
  const [path, setPath] = useState(current ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const qc = useQueryClient();
  const toast = useToast();

  const save = async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      await put("/api/build/paths", { key: itemKey, path: value });
      await qc.invalidateQueries({ queryKey: ["toolchain"] });
      if (itemKey === "mysql") for (const key of ["db-setup", "status"]) qc.invalidateQueries({ queryKey: [key] });
      toast({ tone: "ok", title: value ? `${title}: path saved` : `${title}: back to the detected path` });
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const others = candidates.filter((c) => c.path.toLowerCase() !== path.toLowerCase());
  return (
    <Modal
      open
      wide
      title={`${title}: change ${kind === "file" ? "file" : kind === "instance" ? "installation" : "folder"}`}
      onClose={onClose}
      footer={
        <>
          {origin === "override" && detected && (
            <Button variant="ghost" icon={<RotateCcw className="size-3.5" />} className="mr-auto" loading={busy} onClick={() => save("")}>
              Reset to detected
            </Button>
          )}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant="primary" loading={busy} disabled={!path.trim()} onClick={() => save(path)}>Save</Button>
        </>
      }
    >
      <Field label={kind === "file" ? "File" : "Folder"} hint={hint ?? "Kept until you reset it. Every build uses it."}>
        <PathInput value={path} onChange={setPath} mode={kind === "file" ? "file" : "folder"} ext={kind === "file" ? ".exe" : undefined} autoFocus />
      </Field>
      {others.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-medium text-muted">Also found on this PC</div>
          <div className="space-y-1.5">
            {others.map((c) => (
              <button
                key={c.path}
                onClick={() => setPath(c.path)}
                className="flex w-full items-center justify-between gap-3 rounded-md border border-line px-3 py-2 text-left hover:border-line-strong"
              >
                <span className="truncate font-mono text-xs">{c.path}</span>
                {c.version && <span className="shrink-0 text-xs text-muted">{c.version}</span>}
              </button>
            ))}
          </div>
        </div>
      )}
      {error && <Callout tone="bad">{error}</Callout>}
    </Modal>
  );
}
