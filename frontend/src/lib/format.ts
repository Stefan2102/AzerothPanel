export function bytes(n: number | null | undefined): string {
  if (n == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

export function duration(seconds: number | null | undefined): string {
  if (seconds == null || seconds < 0) return "—";
  const s = Math.floor(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

export function uptime(startedAt: number | null | undefined): string {
  return startedAt ? duration(Date.now() / 1000 - startedAt) : "—";
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "never";
  return `${duration(Date.now() / 1000 - ts)} ago`;
}

export function dateTime(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return isNaN(d.getTime()) ? String(value) : d.toLocaleString();
}

export function date(value: string | number | null | undefined): string {
  if (value == null || value === "") return "—";
  const d = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  return isNaN(d.getTime()) ? String(value) : d.toLocaleDateString();
}

export function money(copper: number): string {
  const g = Math.floor(copper / 10000);
  const s = Math.floor((copper % 10000) / 100);
  const c = copper % 100;
  return `${g}g ${s}s ${c}c`;
}

export function percent(v: number | null | undefined): string {
  return v == null ? "—" : `${v.toFixed(1)}%`;
}
