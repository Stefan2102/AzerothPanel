import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { ArrowUp, Computer, Download, File, FileText, Folder, FolderOpen, FolderPlus, HardDrive, House, Monitor, type LucideIcon } from "lucide-react";
import { get, post } from "../lib/api";
import { Button, Callout, cx, Input, Modal, Spinner } from "./ui";

type Kind = "drive" | "home" | "desktop" | "documents" | "downloads";

interface Listing {
  path: string;
  parent: string | null;
  entries: { name: string; path: string; dir: boolean; kind?: Kind }[];
  /** Quick places: the Windows user's main folders, then every drive. */
  places: { name: string; path: string; kind: Kind }[];
  drives: { name: string; path: string; kind: Kind }[];
}

const KIND_ICON: Record<Kind, LucideIcon> = { drive: HardDrive, home: House, desktop: Monitor, documents: FileText, downloads: Download };

function KindIcon({ kind, className }: { kind: Kind; className: string }) {
  const Icon = KIND_ICON[kind] ?? Folder;
  return <Icon className={className} />;
}

/**
 * Browse the folders of the PC the panel runs on (a web page can't open the PC's own folder dialog).
 * mode "folder" picks the current folder; mode "file" picks a file (optionally only `ext`, e.g. ".exe").
 */
export function PathBrowser({ start, mode = "folder", ext, title, onPick, onClose }: {
  start: string;
  mode?: "folder" | "file";
  ext?: string;
  title?: string;
  onPick: (path: string) => void;
  onClose: () => void;
}) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState<string | null>(null);
  const [newName, setNewName] = useState<string | null>(null);

  const open = useCallback(async (path: string, fallback = true) => {
    setLoading(true);
    setError(null);
    setFile(null);
    try {
      const q = `path=${encodeURIComponent(path)}${mode === "file" ? `&files=true&ext=${encodeURIComponent(ext ?? "")}` : ""}`;
      setListing(await get<Listing>(`/api/fs/list?${q}`));
    } catch (e) {
      // A typed path that doesn't exist yet: show its nearest existing parent, else the drives.
      const parent = path.replace(/[\\/][^\\/]*[\\/]?$/, "");
      if (fallback && parent && parent !== path && /^[A-Za-z]:/.test(parent)) await open(parent.length === 2 ? parent + "\\" : parent, true);
      else if (fallback && path) await open("", false);
      else setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [mode, ext]);

  useEffect(() => {
    open(start.trim());
  }, [open, start]);

  const createFolder = async () => {
    if (!listing?.path || !newName?.trim()) return;
    try {
      const r = await post<{ path: string }>("/api/fs/mkdir", { parent: listing.path, name: newName.trim() });
      setNewName(null);
      await open(r.path, false);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const atDrives = listing?.path === "";
  return (
    <Modal
      open
      wide
      title={title ?? (mode === "file" ? "Choose a file" : "Choose a folder")}
      onClose={onClose}
      footer={
        <>
          {listing?.path && newName === null && (
            <Button variant="ghost" className="mr-auto" icon={<FolderPlus className="size-4" />} onClick={() => setNewName("")}>New folder</Button>
          )}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          {mode === "folder" ? (
            <Button variant="primary" icon={<FolderOpen className="size-4" />} disabled={!listing?.path} onClick={() => listing && onPick(listing.path)}>
              Select this folder
            </Button>
          ) : (
            <Button variant="primary" icon={<File className="size-4" />} disabled={!file} onClick={() => file && onPick(file)}>Select file</Button>
          )}
        </>
      }
    >
      <div className="flex items-center gap-2">
        <Button size="sm" variant="ghost" icon={<ArrowUp className="size-3.5" />} disabled={!listing || atDrives}
          onClick={() => listing && open(listing.parent ?? "", false)}>
          Up
        </Button>
        <div className="min-w-0 flex-1 truncate rounded-md border border-line bg-card-2 px-3 py-1.5 font-mono text-xs" title={listing?.path}>
          {atDrives ? "This PC" : listing?.path ?? "…"}
        </div>
      </div>
      {listing && (
        <div className="flex flex-wrap gap-1">
          <Button size="sm" variant="ghost" icon={<Computer className="size-3.5" />} disabled={atDrives} onClick={() => open("", false)}>This PC</Button>
          {[...listing.places, ...listing.drives].map((d) => (
            <Button key={d.path} size="sm" variant="ghost" icon={<KindIcon kind={d.kind} className="size-3.5" />} title={d.path}
              onClick={() => open(d.path, false)}>{d.name}</Button>
          ))}
        </div>
      )}
      {newName !== null && (
        <div className="flex gap-2">
          <Input autoFocus placeholder="New folder name" value={newName} onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") createFolder(); if (e.key === "Escape") setNewName(null); }} />
          <Button onClick={createFolder} disabled={!newName.trim()}>Create</Button>
          <Button variant="ghost" onClick={() => setNewName(null)}>Cancel</Button>
        </div>
      )}
      {error && <Callout tone="bad">{error}</Callout>}
      <div className="h-80 overflow-y-auto rounded-lg border border-line">
        {loading && !listing ? (
          <div className="p-4"><Spinner /></div>
        ) : listing?.entries.length === 0 ? (
          <p className="p-4 text-xs text-faint">{mode === "file" ? "No matching files or folders here." : "No folders here."}</p>
        ) : (
          listing?.entries.map((e) => (
            <button
              key={e.path}
              onClick={() => (e.dir ? open(e.path, false) : setFile(e.path))}
              onDoubleClick={() => !e.dir && onPick(e.path)}
              className={cx("flex w-full items-center gap-2 border-b border-line px-3 py-2 text-left text-[13px] last:border-b-0 hover:bg-card-2",
                file === e.path && "bg-accent-soft text-accent-text")}
            >
              {e.kind ? <KindIcon kind={e.kind} className="size-4 shrink-0 text-muted" /> : e.dir ? <Folder className="size-4 shrink-0 text-accent-text" /> : <File className="size-4 shrink-0 text-muted" />}
              <span className="truncate">{e.name}</span>
            </button>
          ))
        )}
      </div>
    </Modal>
  );
}

/** A path text field with a Browse button. */
export function PathInput({ value, onChange, mode = "folder", ext, placeholder, disabled, title, autoFocus }: {
  value: string;
  onChange: (path: string) => void;
  mode?: "folder" | "file";
  ext?: string;
  placeholder?: string;
  disabled?: boolean;
  title?: string;
  autoFocus?: boolean;
}) {
  const [browsing, setBrowsing] = useState(false);
  return (
    <div className="flex gap-2">
      <Input className="font-mono" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} disabled={disabled} autoFocus={autoFocus} />
      <Button icon={<FolderOpen className="size-4" />} disabled={disabled} onClick={() => setBrowsing(true)}>Browse</Button>
      {/* Rendered at the page root: fields usually sit in a <label>, which would take the dialog's clicks. */}
      {browsing && createPortal(
        <PathBrowser start={value} mode={mode} ext={ext} title={title}
          onPick={(p) => { onChange(p); setBrowsing(false); }} onClose={() => setBrowsing(false)} />,
        document.body,
      )}
    </div>
  );
}
