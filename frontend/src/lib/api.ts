export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

type Method = "GET" | "POST" | "PUT" | "DELETE";

export async function api<T = unknown>(path: string, method: Method = "GET", body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && !path.startsWith("/api/auth/")) {
    window.dispatchEvent(new Event("acp:unauthorized"));
  }
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const detail = data?.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d) => d.msg).join(", ") : res.statusText;
    throw new ApiError(res.status, message);
  }
  return data as T;
}

export const get = <T>(path: string) => api<T>(path);
export const post = <T>(path: string, body: unknown = {}) => api<T>(path, "POST", body);
export const put = <T>(path: string, body: unknown) => api<T>(path, "PUT", body);
export const del = <T>(path: string) => api<T>(path, "DELETE");

export function wsUrl(path: string): string {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}

// ---- shared response types ---------------------------------------------------

export type ServiceKey = "mysql" | "auth" | "world";
export type ServiceState = "stopped" | "starting" | "running" | "stopping" | "external";

export interface Sample {
  t: number;
  cpu: number;
  mem: number;
}

export interface ServiceStatus {
  key: ServiceKey;
  label: string;
  managed: boolean;
  state: ServiceState;
  owned: boolean;
  pid: number | null;
  started_at: number | null;
  port: number | null;
  cpu: number | null;
  memory: number | null;
  history: Sample[];
  message: string | null;
  last_exit: { code: number | null; at: number; unexpected: boolean } | null;
}

export interface Job {
  name: string;
  step: string | null;
  started: number;
}

export interface Status {
  configured: boolean;
  services: Record<ServiceKey, ServiceStatus>;
  job: Job | null;
  last_job: { name: string; ok: boolean; error: string | null; finished: number } | null;
  counts: { online: number; characters: number; accounts: number } | null;
  /** Where GM commands can go right now: SOAP (preferred) and/or the worldserver console. */
  commands: { available: boolean; soap: boolean; console: boolean };
  /** The running build/deploy job (Compilation page), if any. */
  build: { id: number; type: "build" | "deploy" | "pull"; step: string | null; progress: number } | null;
  /** The running client-data download/extraction (Data Extraction page), if any. */
  data: { id: number; type: "download" | "extract"; step: string | null; progress: number } | null;
  /** The running module install/update/remove (Modules page), if any. */
  modules: { id: number; type: string; step: string | null; progress: number; name?: string | null; detail?: string | null } | null;
  /** The running source clone (Setup page), if any. */
  source: { id: number; type: string; step: string | null; progress: number } | null;
  /** The running SQL import (Database page), if any. */
  sqlimport: { id: number; type: string; step: string | null; progress: number; detail?: string | null } | null;
}

export interface Shortcut {
  id: string;
  name: string;
  path: string;
  args: string;
}

export interface ShortcutsState {
  items: Shortcut[];
  /** Programs found on this PC; a path may be a folder the user picks the file in. */
  suggestions: Omit<Shortcut, "id">[];
}

export interface CommandResult {
  output: string;
  ok: boolean;
  via: "soap" | "console";
}

export const SERVICE_ORDER: ServiceKey[] = ["world", "auth", "mysql"];
