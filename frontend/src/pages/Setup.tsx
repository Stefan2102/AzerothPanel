import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, ExternalLink, FolderPen, Info, RefreshCw, XCircle } from "lucide-react";
import { useToolchain, type ToolItem } from "../lib/build";
import { DatabaseSetup } from "../components/DatabaseSetup";
import { RootFolderForm } from "../components/RootFolder";
import { SourceSetup } from "../components/SourceSetup";
import { OriginTag, PathModal, StatusChip } from "../components/Toolchain";
import { Badge, Button, buttonClass, Callout, Card, CardHeader, cx, PageHeader, Spinner } from "../components/ui";

function RequirementRow({ item }: { item: ToolItem }) {
  const [open, setOpen] = useState(item.status !== "ok");
  const [editing, setEditing] = useState(false);
  const good = item.status === "ok";
  return (
    <div className="border-b border-line last:border-b-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3">
        {good ? <CheckCircle2 className="size-4 shrink-0 text-ok" /> : <XCircle className="size-4 shrink-0 text-bad" />}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-[13px] font-medium">{item.label}</span>
            {item.version && <span className="font-mono text-xs text-muted">{item.version}</span>}
            {item.required && <span className="text-xs text-faint">needs ≥ {item.required}</span>}
          </div>
          {item.path && (
            <div className="mt-0.5 flex min-w-0 items-center gap-2">
              <span className="truncate font-mono text-xs text-muted" title={item.path}>{item.path}</span>
              <OriginTag origin={item.origin} />
            </div>
          )}
        </div>
        <StatusChip item={item} />
        {item.path_kind && (
          <Button size="sm" variant="ghost" icon={<FolderPen className="size-3.5" />} onClick={() => setEditing(true)}>
            Change
          </Button>
        )}
        <a href={item.link} target="_blank" rel="noreferrer noopener" title={item.link_label} className={buttonClass("default", "sm")}>
          <ExternalLink className="size-3.5" /> Download
        </a>
        {item.more_links.map((l) => (
          <a key={l.link} href={l.link} target="_blank" rel="noreferrer noopener" title={l.title} className={buttonClass("default", "sm")}>
            <ExternalLink className="size-3.5" /> {l.label}
          </a>
        ))}
        <button onClick={() => setOpen(!open)} className="rounded p-1 text-muted hover:bg-card-2 hover:text-text" aria-label="Installation notes">
          {open ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
        </button>
      </div>
      {(item.message || item.advice.length > 0) && (
        <div className="space-y-1 px-4 pb-3 pl-11">
          {item.message && !good && <div className="text-xs text-bad">{item.message}</div>}
          {item.advice.map((a, i) => (
            <div key={i} className={cx("flex items-start gap-1.5 text-xs", a.tone === "warn" ? "text-warn" : "text-muted")}>
              {a.tone === "warn" ? <AlertTriangle className="mt-px size-3.5 shrink-0" /> : <Info className="mt-px size-3.5 shrink-0" />}
              {a.text}
            </div>
          ))}
        </div>
      )}
      {open && (
        <div className="mx-4 mb-3 ml-11 rounded-lg border border-line bg-card-2 px-4 py-3">
          <div className="mb-1.5 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs font-medium">What to select during installation</span>
            <span className="text-xs text-faint">Needed for: {item.needed_for}</span>
          </div>
          <ul className="list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted">
            {item.notes.map((n, i) => <li key={i}>{n}</li>)}
          </ul>
        </div>
      )}
      {editing && item.path_kind && (
        <PathModal
          itemKey={item.key}
          title={item.label}
          kind={item.path_kind}
          current={item.path}
          origin={item.origin}
          candidates={item.candidates}
          detected={item.key !== "mysql"}
          hint={item.key === "mysql"
            ? "The extracted MySQL ZIP (the folder with bin\\mysqld.exe) or any folder above it. Compiling, the database server, backups and SQL import use it."
            : undefined}
          onClose={() => setEditing(false)}
        />
      )}
    </div>
  );
}

export function Setup() {
  const { data, isLoading, isFetching, refetch, error } = useToolchain();
  if (isLoading) return <Spinner />;
  if (error || !data) return <Callout tone="bad">{(error as Error)?.message ?? "Couldn't check the requirements."}</Callout>;

  const ready = data.items.filter((i) => i.status === "ok").length;
  return (
    <>
      <PageHeader title="Setup" subtitle="Everything AzerothCore needs on this PC: tools, source code and the database" />
      <Card className="mb-4">
        <CardHeader title="AzerothCore folder" subtitle="Where AzerothCore lives on this PC: its source, build, server and MySQL are kept in this folder." />
        <div className="p-4"><RootFolderForm /></div>
      </Card>
      <Card>
        <CardHeader
          title="Requirements"
          subtitle="Install these yourself from the official sites. The panel finds them and checks the versions against your AzerothCore source."
          right={
            <div className="flex shrink-0 items-center gap-2">
              <Badge tone={ready === data.items.length ? "ok" : "warn"}>{ready} of {data.items.length} ready</Badge>
              <Button size="sm" variant="ghost" icon={<RefreshCw className={cx("size-3.5", isFetching && "animate-spin")} />} onClick={() => refetch()}>
                Re-check
              </Button>
            </div>
          }
        />
        {!data.workspace.source_valid && (
          <div className="border-b border-line px-4 py-3">
            <Callout tone="accent">
              Minimum versions come from the AzerothCore source. Clone it below (Source code) to check them.
            </Callout>
          </div>
        )}
        {data.items.map((item) => <RequirementRow key={item.key} item={item} />)}
      </Card>
      <div className="mt-4">
        <SourceSetup />
      </div>
      <div className="mt-4">
        <DatabaseSetup />
      </div>
    </>
  );
}
