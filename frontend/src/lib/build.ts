import { useQuery } from "@tanstack/react-query";
import { get } from "./api";

export type ItemStatus = "ok" | "too_old" | "missing" | "invalid" | "unknown";
export type PathKind = "folder" | "file" | "instance" | null;

/** One dependency row (backend/services/toolchain.py Item + requirements.GUIDE). */
export interface ToolItem {
  key: string;
  label: string;
  link: string;
  /** What the Download button opens (its tooltip), e.g. "mysql-8.4.11-winx64.zip". */
  link_label: string;
  /** Other downloads of the same requirement (e.g. VS Build Tools), shown as extra buttons. */
  more_links: { label: string; link: string; title: string }[];
  notes: string[];
  needed_for: string;
  path_kind: PathKind;
  path: string | null;
  origin: "override" | "build" | "detected" | null;
  version: string | null;
  required: string | null;
  status: ItemStatus;
  message: string | null;
  advice: { tone: "info" | "warn"; text: string }[];
  candidates: { path: string; version?: string | null }[];
  details: Record<string, unknown>;
}

export interface ModuleInfo {
  name: string;
  link: string | null;
  broken: boolean;
  git: boolean;
  branch?: string | null;
  commit?: string | null;
  remote?: string | null;
  dirty?: boolean | null;
}

export interface Revision {
  git: boolean;
  branch?: string | null;
  commit?: string | null;
  date?: string | null;
  subject?: string | null;
  remote?: string | null;
  dirty?: boolean | null;
}

export interface BuildOptions {
  config: string;
  jobs: number;
  TOOLS_BUILD: string | null;
  SCRIPTS: string | null;
  MODULES: string | null;
  clean: boolean;
  deploy: boolean;
}

export interface Toolchain {
  workspace: {
    /** Fixed places in the AzerothCore folder; null until it is chosen. */
    source: string | null;
    source_valid: boolean;
    build: string | null;
    install: string | null;
    revision: Revision | null;
    modules: ModuleInfo[];
    choices: Record<string, { choices: string[]; default: string | null }>;
  };
  items: ToolItem[];
  ready: boolean;
  /** Deploy only needs less than a build (e.g. a broken module link doesn't matter). */
  deploy_ready: boolean;
  problems: string[];
  options: BuildOptions;
  configs: string[];
  /** CPU threads of the PC the panel runs on (the default for parallel jobs); null if unknown. */
  cpu_threads: number | null;
  built: string[];
  busy: boolean;
}

export interface BuildJob {
  id: number;
  type: "build" | "deploy" | "pull";
  status: "running" | "completed" | "failed" | "cancelled";
  started: number;
  finished: number | null;
  error: string | null;
  options: Partial<BuildOptions>;
  step: "pull" | "configure" | "build" | "deploy" | "done" | null;
  progress: number;
  projects_done: number;
  projects_total: number;
  files_done?: number;
  files_total?: number;
  /** Nothing compiled yet in the build folder: all files_total files compile. Otherwise up-to-date ones are skipped. */
  fresh?: boolean;
  warnings: number;
  errors: number;
  deployed: boolean;
  /** Configs this deploy created or replaced from their templates (they need Config Files -> Save & apply). */
  configs?: string[];
  duration: number | null;
  /** Pull jobs: number of new commits. */
  commits?: number;
  log?: string[];
  log_first?: number;
  log_total?: number;
}

export function useToolchain() {
  return useQuery({ queryKey: ["toolchain"], queryFn: () => get<Toolchain>("/api/build/toolchain"), refetchOnWindowFocus: true });
}

export const ORIGIN_LABEL: Record<string, string> = {
  override: "your choice",
  build: "from your existing build",
  detected: "detected",
};
