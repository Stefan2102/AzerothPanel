import { lazy, Suspense, useEffect, type ComponentType } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { get } from "./lib/api";
import { useRoute, useStatus } from "./lib/hooks";
import { Layout } from "./components/Layout";
import { Spinner } from "./components/ui";
import { Backups } from "./pages/Backups";
import { Dashboard } from "./pages/Dashboard";
import { ChangeDefaultPassword, Login } from "./pages/Login";
import { Logs } from "./pages/Logs";
import { Players } from "./pages/Players";
import { ServerControl } from "./pages/ServerControl";
import { Settings } from "./pages/Settings";

// Pages with CodeMirror load on demand to keep the first paint small.
// After a rebuild the old chunk names no longer exist; reload once to pick up the new build.
function lazyPage<T extends Record<string, ComponentType>>(load: () => Promise<T>, name: keyof T) {
  return lazy(() =>
    load().then(
      (m) => {
        sessionStorage.removeItem("acp-reloaded");
        return { default: m[name] };
      },
      (err) => {
        if (!sessionStorage.getItem("acp-reloaded")) {
          sessionStorage.setItem("acp-reloaded", "1");
          location.reload();
        }
        throw err;
      },
    ),
  );
}
const Configs = lazyPage(() => import("./pages/Configs"), "Configs");
const Console = lazyPage(() => import("./pages/Console"), "Console");
const Database = lazyPage(() => import("./pages/Database"), "Database");
const Setup = lazyPage(() => import("./pages/Setup"), "Setup");
const Compilation = lazyPage(() => import("./pages/Compilation"), "Compilation");
const DataExtraction = lazyPage(() => import("./pages/DataExtraction"), "DataExtraction");
const Modules = lazyPage(() => import("./pages/Modules"), "Modules");

const PAGES: Record<string, ComponentType> = {
  "/": Dashboard,
  "/console": Console,
  "/logs": Logs,
  "/server": ServerControl,
  "/players": Players,
  "/database": Database,
  "/backups": Backups,
  "/setup": Setup,
  "/compilation": Compilation,
  "/data-extraction": DataExtraction,
  "/modules": Modules,
  "/configs": Configs,
  "/settings": Settings,
};

/** Pages that need the AzerothCore folder to be set. */
const NEEDS_CONFIG = new Set(["/console", "/logs", "/players", "/database", "/configs", "/data-extraction"]);

function Shell({ username, onLogout }: { username: string; onLogout: () => void }) {
  const [route, go] = useRoute();
  const { data: status } = useStatus();
  const configured = status?.configured;

  useEffect(() => {
    if (configured === false && NEEDS_CONFIG.has(route)) go("/settings");
  }, [configured, route, go]);

  const Page = PAGES[route] ?? Dashboard;
  return (
    <Layout route={route} username={username} onLogout={onLogout}>
      <Suspense fallback={<Spinner />}>
        <Page />
      </Suspense>
    </Layout>
  );
}

export function App() {
  const qc = useQueryClient();
  const auth = useQuery({
    queryKey: ["auth"],
    queryFn: () => get<{ authenticated: boolean; username: string | null; must_change_password: boolean }>("/api/auth/state"),
    staleTime: Infinity,
  });

  useEffect(() => {
    const onUnauthorized = () => qc.invalidateQueries({ queryKey: ["auth"] });
    window.addEventListener("acp:unauthorized", onUnauthorized);
    return () => window.removeEventListener("acp:unauthorized", onUnauthorized);
  }, [qc]);

  if (auth.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  if (auth.isError) {
    return <div className="flex h-full items-center justify-center text-muted">The panel backend isn't reachable. Start it with start.bat.</div>;
  }
  const refresh = () => qc.invalidateQueries({ queryKey: ["auth"] });
  if (!auth.data?.authenticated) {
    return <Login onDone={refresh} />;
  }
  if (auth.data.must_change_password) {
    return <ChangeDefaultPassword onDone={refresh} />;
  }
  const logout = () => {
    // Show the login screen right away and drop everything loaded while signed in.
    qc.setQueryData(["auth"], { authenticated: false, username: null, must_change_password: false });
    qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "auth" });
  };
  return <Shell username={auth.data.username ?? ""} onLogout={logout} />;
}
