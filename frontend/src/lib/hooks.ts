import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get, post, type ServiceKey, type Status } from "./api";
import { useConfirm, useToast } from "../components/ui";

export function useStatus() {
  return useQuery({
    queryKey: ["status"],
    queryFn: () => get<Status>("/api/status"),
    refetchInterval: 2000,
  });
}

export function useRoute(): [string, (to: string) => void] {
  const read = () => location.hash.replace(/^#/, "") || "/";
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const onHash = () => setRoute(read());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return [route, (to: string) => (location.hash = to)];
}

/** Lifecycle actions. Only restart and force kill ask for confirmation. */
export function useServerActions() {
  const confirm = useConfirm();
  const toast = useToast();
  const qc = useQueryClient();

  const run = async (path: string, body: unknown, what: string) => {
    try {
      await post(path, body);
      toast({ tone: "accent", title: what });
    } catch (e) {
      toast({ tone: "bad", title: `${what} failed`, body: (e as Error).message });
    }
    qc.invalidateQueries({ queryKey: ["status"] });
  };

  return {
    start: (key: ServiceKey, label: string) => run(`/api/server/${key}/start`, {}, `Starting ${label}`),
    // Stops are always graceful (see docs/process-control.md), so they run without a confirmation.
    stop: (key: ServiceKey, label: string, delay?: number) => run(`/api/server/${key}/stop`, { delay: delay ?? null }, `Stopping ${label}`),
    restart: async (key: ServiceKey, label: string) => {
      const ok = await confirm({
        title: `Restart ${label}?`,
        body: `${label} will be stopped safely and started again.`,
        confirm: "Restart",
      });
      if (ok) await run(`/api/server/${key}/restart`, {}, `Restarting ${label}`);
    },
    kill: async (key: ServiceKey, label: string) => {
      const ok = await confirm({
        title: `Force kill ${label}?`,
        body: "This terminates the process immediately. Unsaved player progress is lost and MySQL may need crash recovery. Only use this if a safe stop is stuck.",
        confirm: "Force kill",
        danger: true,
      });
      if (ok) await run(`/api/server/${key}/kill`, { confirm: true }, `Force-killed ${label}`);
    },
    startAll: () => run("/api/server/start-all", {}, "Starting all servers"),
    stopAll: () => run("/api/server/stop-all", {}, "Stopping all servers"),
  };
}
