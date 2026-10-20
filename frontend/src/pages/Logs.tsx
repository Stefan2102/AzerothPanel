import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpToLine, Download, FileText, Filter, Search, Trash2, Wifi, WifiOff } from "lucide-react";
import { get, wsUrl } from "../lib/api";
import { Button, Card, cx, Empty, PageHeader, Spinner } from "../components/ui";

interface Source {
  key: string;
  label: string;
  available: boolean;
  reason: string | null;
  file: string | null;
  size: number;
}

interface Page {
  lines: string[];
  start: number;
  end: number;
}

const MAX_LINES = 20000;
const LEVELS = ["ALL", "ERROR", "WARN", "INFO", "DEBUG"] as const;
type Level = (typeof LEVELS)[number];

const LEVEL_WORD = /\b(FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE)\b/i;
const LEVEL_COLOR: Record<string, string> = { ERROR: "text-[#f27474]", WARN: "text-[#e9b44c]", DEBUG: "text-faint" };

/** Level named in the line; otherwise the source's default (Errors.log only receives errors). */
function levelOf(line: string, fallback: Level): Level {
  const m = LEVEL_WORD.exec(line);
  if (!m) return fallback;
  const word = m[1].toUpperCase();
  return word === "FATAL" ? "ERROR" : word === "WARNING" ? "WARN" : word === "TRACE" ? "DEBUG" : (word as Level);
}

function Pill({ active, onClick, children }: { active: boolean; onClick: () => void; children: string }) {
  return (
    <button
      onClick={onClick}
      className={cx("h-7 rounded-md px-3 text-xs font-medium transition-colors", active ? "bg-accent text-white" : "bg-card-2 text-muted hover:text-text")}
    >
      {children}
    </button>
  );
}

export function Logs() {
  const { data: sources, isLoading } = useQuery({ queryKey: ["logs"], queryFn: () => get<Source[]>("/api/logs"), refetchInterval: 10000 });
  const [key, setKey] = useState("worldserver");
  const [level, setLevel] = useState<Level>("ALL");
  const [search, setSearch] = useState("");
  const [lines, setLines] = useState<string[]>([]);
  const [start, setStart] = useState(0);
  const [connected, setConnected] = useState(false);
  const [autoScroll, setAutoScroll] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const box = useRef<HTMLDivElement>(null);

  const source = sources?.find((s) => s.key === key);
  const available = !!source?.available;
  const fallback: Level = key === "db_errors" ? "ERROR" : "INFO";

  // Last 1000 lines, then live follow from where they ended. Reconnects if the socket drops.
  useEffect(() => {
    setLines([]);
    setStart(0);
    setConnected(false);
    if (!available) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const follow = (offset: number) => {
      ws = new WebSocket(wsUrl(`/ws/logs/${key}?offset=${offset}`));
      ws.onopen = () => setConnected(true);
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.t === "reset") {
          setLines(["──── log file was restarted ────"]);
          setStart(0);
        } else if (msg.t === "lines") {
          offset = msg.offset;
          setLines((prev) => {
            const next = prev.concat(msg.d);
            return next.length > MAX_LINES ? next.slice(next.length - MAX_LINES) : next;
          });
        }
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(() => follow(offset), 2000);
      };
    };

    get<Page>(`/api/logs/${key}?limit=1000`)
      .then((page) => {
        if (closed) return;
        setLines(page.lines);
        setStart(page.start);
        follow(page.end);
      })
      .catch(() => setConnected(false));
    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [key, available]);

  const shown = useMemo(() => {
    const f = search.toLowerCase();
    return lines.filter((l) => (level === "ALL" || levelOf(l, fallback) === level) && (!f || l.toLowerCase().includes(f)));
  }, [lines, level, search, fallback]);

  useEffect(() => {
    if (autoScroll && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [shown, autoScroll]);

  const loadOlder = async () => {
    if (start === 0) return;
    setLoadingOlder(true);
    const el = box.current;
    const prevHeight = el?.scrollHeight ?? 0;
    try {
      const page = await get<Page>(`/api/logs/${key}?before=${start}&limit=2000`);
      setLines((prev) => page.lines.concat(prev));
      setStart(page.start);
      requestAnimationFrame(() => {
        if (el) el.scrollTop = el.scrollHeight - prevHeight;
      });
    } finally {
      setLoadingOlder(false);
    }
  };

  if (isLoading || !sources) return <Spinner />;

  return (
    <div className="flex h-full flex-col gap-4">
      <PageHeader title="Logs" subtitle="Live log streaming from worldserver and authserver log files" />
      <Card className="-mt-1 flex flex-wrap items-center gap-3 p-3">
        <div className="flex gap-1">
          {sources.map((s) => (
            <Pill key={s.key} active={key === s.key} onClick={() => setKey(s.key)}>
              {s.label}
            </Pill>
          ))}
        </div>
        <div className="h-4 border-l border-line" />
        <div className="flex items-center gap-1">
          <Filter className="size-3.5 text-muted" />
          {LEVELS.map((l) => (
            <button
              key={l}
              onClick={() => setLevel(l)}
              className={cx("h-7 rounded px-2.5 text-xs font-medium transition-colors", level === l ? "bg-accent-soft text-accent-text" : "text-muted hover:text-text")}
            >
              {l}
            </button>
          ))}
        </div>
        <div className="flex h-8 min-w-36 flex-1 items-center gap-2 rounded-lg border border-line bg-card-2 px-2.5">
          <Search className="size-3.5 shrink-0 text-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search logs…"
            className="flex-1 bg-transparent text-xs text-text outline-none placeholder:text-faint"
          />
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className={cx("flex items-center gap-1.5 text-xs", connected ? "text-ok" : "text-bad")}>
            {connected ? <Wifi className="size-3.5" /> : <WifiOff className="size-3.5" />}
            {connected ? "Live" : "Disconnected"}
          </span>
          <Button size="sm" variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => setLines([])}>
            Clear
          </Button>
          <a href={available ? `/api/logs/${key}/download` : undefined}>
            <Button size="sm" icon={<Download className="size-3.5" />} disabled={!available}>
              Download
            </Button>
          </a>
        </div>
      </Card>

      <Card className="flex min-h-[420px] flex-1 flex-col overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-4 py-2">
          {available && start > 0 ? (
            <button onClick={loadOlder} className="flex items-center gap-1.5 text-xs text-accent-text hover:underline">
              {loadingOlder ? <Spinner className="size-3" /> : <ArrowUpToLine className="size-3" />} Load older lines
            </button>
          ) : (
            <span />
          )}
          <button
            onClick={() => setAutoScroll((v) => !v)}
            className={cx("rounded px-2 py-1 text-xs", autoScroll ? "bg-ok-soft text-ok" : "bg-card-2 text-muted")}
          >
            {autoScroll ? "Auto-scroll ON" : "Auto-scroll OFF"}
          </button>
        </div>
        {available ? (
          <div ref={box} className="min-h-0 flex-1 overflow-auto bg-term px-4 py-2 font-mono text-xs leading-5">
            {shown.map((l, i) => (
              <div key={i} className={cx("break-all whitespace-pre-wrap", LEVEL_COLOR[levelOf(l, fallback)] ?? "text-[#c9ccd6]")}>
                {l || " "}
              </div>
            ))}
          </div>
        ) : (
          <Empty icon={<FileText className="size-6" />} title={`${source?.label ?? "Log"} isn't available`}>
            {source?.reason}
          </Empty>
        )}
      </Card>
    </div>
  );
}
