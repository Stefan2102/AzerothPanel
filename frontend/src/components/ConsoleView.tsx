import { memo, useEffect, useRef, useState } from "react";
import { wsUrl, type ServiceKey } from "../lib/api";

/** [text, colour, bold]; colour is a pyte name ("brightcyan", "default") or "rrggbb". */
type Segment = [string, string, number];
type Line = Segment[];

const COLORS: Record<string, string> = {
  black: "#5d5f72", red: "#f27474", green: "#3fcf8e", brown: "#e9b44c", blue: "#6ea8fe",
  magenta: "#b2a8ff", cyan: "#5ccfe6", white: "#d6d8e1",
  brightblack: "#8a8ca0", brightred: "#ff9a9a", brightgreen: "#6ee7b0", brightbrown: "#ffd479",
  brightblue: "#9cc4ff", brightmagenta: "#cfc8ff", brightcyan: "#8ee3f5", brightwhite: "#ffffff",
};
const MAX_LINES = 10000;
const CHUNK = 500;

function color(name: string): string | undefined {
  if (!name || name === "default") return undefined;
  return COLORS[name] ?? (/^[0-9a-f]{6}$/i.test(name) ? `#${name}` : undefined);
}

function LineRow({ line }: { line: Line }) {
  if (!line.length) return <div>&nbsp;</div>;
  return (
    <div>
      {line.map(([text, fg, bold], i) => (
        <span key={i} style={{ color: color(fg), fontWeight: bold ? 600 : undefined }}>
          {text}
        </span>
      ))}
    </div>
  );
}

/** A block of finished lines. Finished lines never change, so a block re-renders only when it grows. */
const Chunk = memo(
  function Chunk({ lines, start, end }: { lines: Line[]; start: number; end: number; run: number }) {
    const rows = [];
    for (let i = start; i < end; i++) rows.push(<LineRow key={i} line={lines[i]} />);
    return <>{rows}</>;
  },
  (a, b) => a.start === b.start && a.end === b.end && a.run === b.run,
);

/** Live, read-only server console (lines are interpreted server-side). */
export function ConsoleView({ service }: { service: ServiceKey }) {
  const box = useRef<HTMLDivElement>(null);
  const lines = useRef<Line[]>([]);
  const stick = useRef(true);
  const [screen, setScreen] = useState<Line[]>([]);
  const [count, setCount] = useState(0);
  const [run, setRun] = useState(0);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let runCounter = 0;

    const connect = () => {
      ws = new WebSocket(wsUrl(`/ws/console/${service}`));
      ws.onopen = () => setConnected(true);
      ws.onmessage = (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.t === "init") {
          lines.current = msg.lines.slice(-MAX_LINES);
          setRun(++runCounter); // forces every chunk to re-render with the new content
        } else {
          lines.current.push(...msg.lines);
          if (lines.current.length > MAX_LINES) {
            lines.current = lines.current.slice(-MAX_LINES);
            setRun(++runCounter);
          }
        }
        setCount(lines.current.length);
        setScreen(msg.screen);
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) retry = setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      ws?.close();
    };
  }, [service]);

  useEffect(() => {
    if (stick.current && box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [count, screen]);

  const chunks = [];
  for (let start = 0; start < count; start += CHUNK) {
    chunks.push(<Chunk key={`${run}-${start}`} lines={lines.current} start={start} end={Math.min(start + CHUNK, count)} run={run} />);
  }

  return (
    <div className="relative h-full min-h-0 overflow-hidden rounded-lg border border-line bg-term">
      <div
        ref={box}
        onScroll={(e) => {
          const el = e.currentTarget;
          stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
        }}
        className="h-full overflow-auto px-4 py-3 font-mono text-[13px] leading-5 whitespace-pre-wrap break-words text-[#d6d8e1]"
      >
        {chunks}
        {screen.map((line, i) => (
          <LineRow key={`s${i}`} line={line} />
        ))}
        {count === 0 && screen.length === 0 && <div className="text-faint">No output yet — start the server to see its console here.</div>}
      </div>
      {!connected && <div className="absolute top-2 right-4 rounded bg-black/40 px-2 py-0.5 text-[11px] text-muted">reconnecting…</div>}
    </div>
  );
}
