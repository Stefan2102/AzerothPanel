import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Archive, ChevronLeft, ChevronRight, Database as DbIcon, Play, Search, Table2 } from "lucide-react";
import { get, post } from "../lib/api";
import { bytes } from "../lib/format";
import { CodeEditor } from "../components/CodeEditor";
import { useSqlImport } from "../components/SqlImport";
import { Badge, Button, Callout, Card, cx, Empty, Input, PageHeader, Spinner } from "../components/ui";

interface DbEntry {
  key: string;
  database: string;
}
interface TableEntry {
  name: string;
  row_estimate: number | null;
  size: number | null;
}
interface Column {
  name: string;
  type: string;
  key: string;
}
type Cell = string | number | null;
interface Result {
  columns: string[];
  rows: Cell[][];
  truncated?: boolean;
  elapsed_ms?: number;
  total?: number;
  page?: number;
  size?: number;
}

function ResultTable({ result }: { result: Result }) {
  if (!result.columns.length) return <Empty title="Statement executed">No result set.</Empty>;
  return (
    <div className="min-h-0 flex-1 overflow-auto">
      <table className="w-max min-w-full font-mono text-xs">
        <thead className="sticky top-0 bg-card-2">
          <tr>
            {result.columns.map((c) => (
              <th key={c} className="border-b border-line px-3 py-2 text-left font-semibold whitespace-nowrap text-muted">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {result.rows.map((row, i) => (
            <tr key={i} className="border-b border-line hover:bg-card-2">
              {row.map((v, j) => (
                <td key={j} className="max-w-96 truncate px-3 py-1.5 whitespace-nowrap" title={v == null ? "NULL" : String(v)}>
                  {v == null ? <span className="text-faint">NULL</span> : String(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The editor's starting query for each database; switching database swaps it while it is still unedited. */
const EXAMPLE_SQL: Record<string, string> = {
  auth: "SELECT id, username, last_login FROM account ORDER BY id LIMIT 50;",
  characters: "SELECT guid, name, level, online FROM characters ORDER BY level DESC LIMIT 50;",
  world: "SELECT entry, name, minlevel, maxlevel FROM creature_template ORDER BY entry LIMIT 50;",
};
const exampleSql = (key: string) => EXAMPLE_SQL[key] ?? "SHOW TABLES;";

export function Database() {
  const { data: dbs, error: dbError } = useQuery({ queryKey: ["dbs"], queryFn: () => get<DbEntry[]>("/api/db") });
  const [db, setDb] = useState("characters");
  const [tableFilter, setTableFilter] = useState("");
  const [table, setTable] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [sql, setSql] = useState(exampleSql("characters"));
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const sqlImport = useSqlImport(dbs ?? []);
  const tables = useQuery({ queryKey: ["tables", db], queryFn: () => get<TableEntry[]>(`/api/db/${db}/tables`), retry: false });
  const filtered = useMemo(() => (tables.data ?? []).filter((t) => t.name.includes(tableFilter.toLowerCase())), [tables.data, tableFilter]);

  const openTable = async (name: string, p = 0) => {
    setTable(name);
    setPage(p);
    setError(null);
    setRunning(true);
    try {
      const r = await get<{ columns: Column[]; rows: Cell[][]; total: number; page: number; size: number }>(`/api/db/${db}/tables/${encodeURIComponent(name)}?page=${p}&size=100`);
      setResult({ columns: r.columns.map((c) => c.name), rows: r.rows, total: r.total, page: r.page, size: r.size });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const runQuery = async () => {
    setRunning(true);
    setError(null);
    setTable(null);
    try {
      setResult(await post<Result>(`/api/db/${db}/query`, { sql }));
    } catch (e) {
      setError((e as Error).message);
      setResult(null);
    } finally {
      setRunning(false);
    }
  };

  if (dbError) return <Empty title="Database unavailable">{(dbError as Error).message}</Empty>;
  const dbName = dbs?.find((d) => d.key === db)?.database ?? db;
  const pages = result?.total != null && result.size ? Math.max(1, Math.ceil(result.total / result.size)) : 1;

  return (
    <div className="flex h-full flex-col">
      <PageHeader title="Database" subtitle="Browse tables and run read-only SQL against the auth, characters and world databases" right={sqlImport.button} />
      {sqlImport.output}
      <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
        <Card className="flex min-h-[420px] flex-col overflow-hidden">
          <div className="space-y-0.5 border-b border-line p-2">
            {(dbs ?? []).map((d) => (
              <button
                key={d.key}
                onClick={() => {
                  if (sql.trim() === exampleSql(db)) setSql(exampleSql(d.key));
                  setDb(d.key);
                  setTable(null);
                  setResult(null);
                }}
                className={cx("flex h-9 w-full items-center gap-2 rounded-lg px-3 text-[13px]", db === d.key ? "bg-accent-soft font-medium text-accent-text" : "text-muted hover:bg-card-2 hover:text-text")}
              >
                <DbIcon className="size-4" />
                <span className="capitalize">{d.key}</span>
                <span className="ml-auto truncate text-[11px] text-faint">{d.database}</span>
              </button>
            ))}
          </div>
          <div className="relative border-b border-line p-2">
            <Search className="absolute top-[18px] left-5 size-3.5 text-faint" />
            <Input className="h-8 pl-8 text-xs" placeholder="Filter tables…" value={tableFilter} onChange={(e) => setTableFilter(e.target.value)} />
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto p-1">
            {tables.isLoading && <div className="p-3"><Spinner /></div>}
            {tables.error && (
              <div className="p-2">
                <Callout tone="bad">
                  {(tables.error as Error).message}. Start MySQL in <a className="underline" href="#/server">Server Control</a>, then{" "}
                  <button className="underline" onClick={() => tables.refetch()}>try again</button>.
                </Callout>
              </div>
            )}
            {filtered.map((t) => (
              <button
                key={t.name}
                onClick={() => openTable(t.name)}
                className={cx("flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-left font-mono text-xs", table === t.name ? "bg-card-2 text-text" : "text-muted hover:bg-card-2 hover:text-text")}
                title={`${t.row_estimate ?? 0} rows (estimate) · ${bytes(t.size)}`}
              >
                <Table2 className="size-3.5 shrink-0 opacity-60" />
                <span className="truncate">{t.name}</span>
              </button>
            ))}
          </div>
          <div className="border-t border-line p-2">
            <a href="#/backups">
              <Button className="w-full" size="sm" icon={<Archive className="size-3.5" />}>Backup databases</Button>
            </a>
          </div>
        </Card>

        <div className="flex min-h-0 flex-col gap-4">
          <Card className="overflow-hidden">
            <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
              <div>
                <div className="text-[13px] font-semibold">SQL query editor</div>
                <div className="text-xs text-muted">
                  Executing against <span className="font-mono">{dbName}</span> · read-only · Ctrl+Enter to run
                </div>
              </div>
              <Button variant="primary" size="sm" icon={<Play className="size-3.5" />} loading={running && !table} onClick={runQuery}>
                Run query
              </Button>
            </div>
            <div className="h-40">
              <CodeEditor lang="sql" value={sql} onChange={setSql} onRun={runQuery} />
            </div>
          </Card>

          <Card className="flex min-h-[300px] flex-1 flex-col overflow-hidden">
            <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
              <div className="text-[13px] font-semibold">
                {table ? <>Table <span className="font-mono">{table}</span></> : "Query results"}
              </div>
              <div className="flex items-center gap-2 text-xs text-muted">
                {result && !table && (
                  <>
                    {result.rows.length} rows{result.elapsed_ms != null && ` · ${result.elapsed_ms} ms`}
                    {result.truncated && <Badge tone="warn">first 1000 rows</Badge>}
                  </>
                )}
                {table && result?.total != null && (
                  <>
                    {result.total.toLocaleString()} rows · page {page + 1} / {pages}
                    <Button size="sm" variant="ghost" disabled={page === 0 || running} onClick={() => openTable(table, page - 1)} icon={<ChevronLeft className="size-3.5" />} />
                    <Button size="sm" variant="ghost" disabled={page + 1 >= pages || running} onClick={() => openTable(table, page + 1)} icon={<ChevronRight className="size-3.5" />} />
                  </>
                )}
              </div>
            </div>
            {error && <div className="p-3"><Callout tone="bad">{error}</Callout></div>}
            {running && !result && <div className="p-6"><Spinner /></div>}
            {result ? <ResultTable result={result} /> : !error && !running && <Empty icon={<Table2 className="size-6" />} title="Select a table or run a query to see results" />}
          </Card>
        </div>
      </div>
    </div>
  );
}
