import { useRef, useState, type KeyboardEvent } from "react";
import { post, type CommandResult } from "../lib/api";
import { Button, Input, useToast } from "./ui";

export interface GmReply {
  cmd: string;
  out: string;
  ok: boolean;
  via: CommandResult["via"];
}

const MAX_REPLIES = 20;
const MAX_RECALL = 50;

/** GM command state shared by Server Control and Console: input, replies, Up/Down recall. */
export function useGmCommand() {
  const [cmd, setCmd] = useState("");
  const [busy, setBusy] = useState(false);
  const [replies, setReplies] = useState<GmReply[]>([]);
  const sent = useRef<string[]>([]); // newest last
  const recall = useRef(-1); // index into `sent`, -1 = editing a new line
  const toast = useToast();

  const run = async () => {
    const command = cmd.trim();
    if (!command || busy) return;
    setBusy(true);
    try {
      const r = await post<CommandResult>("/api/server/command", { command });
      setReplies((h) => [{ cmd: command, out: r.output || "(no output)", ok: r.ok, via: r.via }, ...h].slice(0, MAX_REPLIES));
      if (sent.current[sent.current.length - 1] !== command) sent.current = [...sent.current, command].slice(-MAX_RECALL);
      recall.current = -1;
      setCmd("");
    } catch (e) {
      toast({ tone: "bad", title: "Command failed", body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    const list = sent.current;
    if (!list.length) return;
    e.preventDefault();
    let i = recall.current;
    if (e.key === "ArrowUp") i = i === -1 ? list.length - 1 : Math.max(0, i - 1);
    else i = i === -1 ? -1 : i + 1 >= list.length ? -1 : i + 1;
    recall.current = i;
    setCmd(i === -1 ? "" : list[i]);
  };

  const change = (value: string) => {
    recall.current = -1;
    setCmd(value);
  };

  return { cmd, setCmd: change, busy, replies, run, onKeyDown };
}

type GmCommandState = ReturnType<typeof useGmCommand>;

/** Command line + Run button. */
export function GmCommandForm({ gm, disabled, placeholder = ".server info" }: { gm: GmCommandState; disabled: boolean; placeholder?: string }) {
  return (
    <form
      className="flex gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        gm.run();
      }}
    >
      <Input
        className="font-mono"
        placeholder={placeholder}
        value={gm.cmd}
        onChange={(e) => gm.setCmd(e.target.value)}
        onKeyDown={gm.onKeyDown}
        disabled={disabled}
        autoComplete="off"
        spellCheck={false}
      />
      <Button variant="primary" type="submit" loading={gm.busy} disabled={disabled || !gm.cmd.trim()}>
        Run
      </Button>
    </form>
  );
}

/** Replies, newest first. */
export function GmReplies({ replies, className = "max-h-72" }: { replies: GmReply[]; className?: string }) {
  if (!replies.length) return null;
  return (
    <div className={`space-y-3 overflow-y-auto rounded-lg border border-line bg-term p-3 font-mono text-xs ${className}`}>
      {replies.map((h, i) => (
        <div key={i}>
          <div className="text-accent-text">AC&gt; {h.cmd}</div>
          <pre className={`mt-1 whitespace-pre-wrap ${h.ok ? "text-[#d6d8e1]" : "text-[#f27474]"}`}>{h.out}</pre>
        </div>
      ))}
    </div>
  );
}
