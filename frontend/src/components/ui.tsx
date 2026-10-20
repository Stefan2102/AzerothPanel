import { createContext, useCallback, useContext, useEffect, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from "react";
import { AlertTriangle, CheckCircle2, Eye, EyeOff, Info, Loader2, X, XCircle } from "lucide-react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

// ---- buttons ----------------------------------------------------------------

type Variant = "default" | "primary" | "success" | "danger" | "ghost";
const VARIANTS: Record<Variant, string> = {
  default: "border-line-strong bg-card-2 text-text hover:border-faint",
  primary: "border-transparent bg-accent text-white hover:brightness-110",
  success: "border-ok-line bg-ok-soft text-ok hover:brightness-125",
  danger: "border-bad-line bg-bad-soft text-bad hover:brightness-125",
  ghost: "border-transparent bg-transparent text-muted hover:bg-card-2 hover:text-text",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  icon?: ReactNode;
  loading?: boolean;
}

/** Button look, also used for links that open a page (a <button> can't sit inside an <a>). */
export function buttonClass(variant: Variant = "default", size: "sm" | "md" = "md", className?: string) {
  return cx(
    "inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-[filter,background,border-color,color] disabled:cursor-not-allowed disabled:opacity-45 whitespace-nowrap",
    size === "sm" ? "h-7 px-2.5 text-xs" : "h-9 px-3.5 text-[13px]",
    VARIANTS[variant],
    className,
  );
}

export function Button({ variant = "default", size = "md", icon, loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={buttonClass(variant, size, className)}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// ---- surfaces -----------------------------------------------------------------

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cx("rounded-xl border border-line bg-card", className)}>{children}</div>;
}

export function CardHeader({ title, subtitle, right }: { title: ReactNode; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line px-4 py-3">
      <div className="min-w-0">
        <div className="text-[13px] font-semibold">{title}</div>
        {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
      </div>
      {right}
    </div>
  );
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle: string; right?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-lg font-semibold">{title}</h1>
        <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p>
      </div>
      {right && <div className="flex flex-wrap items-center gap-2">{right}</div>}
    </div>
  );
}

type Tone = "ok" | "bad" | "warn" | "accent" | "muted";
const TONES: Record<Tone, string> = {
  ok: "border-ok-line bg-ok-soft text-ok",
  bad: "border-bad-line bg-bad-soft text-bad",
  warn: "border-warn-line bg-warn-soft text-warn",
  accent: "border-transparent bg-accent-soft text-accent-text",
  muted: "border-line bg-card-2 text-muted",
};

export function Badge({ tone = "muted", dot, pulse, children }: { tone?: Tone; dot?: boolean; pulse?: boolean; children: ReactNode }) {
  return (
    <span className={cx("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium whitespace-nowrap", TONES[tone])}>
      {dot && <span className={cx("size-1.5 rounded-full bg-current", pulse && "pulse")} />}
      {children}
    </span>
  );
}

export function Stat({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted">{label}</div>
      <div className={cx("mt-0.5 truncate text-[13px]", mono && "font-mono")}>{value}</div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      {icon && <div className="text-faint">{icon}</div>}
      <div className="text-[13px] font-medium">{title}</div>
      {children && <div className="max-w-md text-xs text-muted">{children}</div>}
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-4 animate-spin text-muted", className)} />;
}

export function Callout({ tone = "warn", children }: { tone?: "warn" | "bad" | "ok" | "accent"; children: ReactNode }) {
  const Icon = tone === "bad" ? XCircle : tone === "ok" ? CheckCircle2 : tone === "accent" ? Info : AlertTriangle;
  return (
    <div className={cx("flex items-start gap-2 rounded-lg border px-3 py-2 text-[13px]", TONES[tone])}>
      <Icon className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0">{children}</div>
    </div>
  );
}

// ---- form controls --------------------------------------------------------------

const FIELD = "h-9 w-full rounded-md border border-line-strong bg-card-2 px-3 text-[13px] text-text placeholder:text-faint outline-none focus:border-accent";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={cx(FIELD, className)} />;
}

/** Password field with an eye button. `onReveal` loads a saved password the field doesn't hold yet;
 * `onHide` lets the owner drop it again (so the hidden field doesn't show its length). */
export function PasswordInput({ className, onReveal, onHide, ...rest }: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { onReveal?: () => Promise<void>; onHide?: () => void }) {
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    if (!shown && onReveal && !rest.value) {
      setBusy(true);
      try {
        await onReveal();
      } finally {
        setBusy(false);
      }
    }
    if (shown) onHide?.();
    setShown(!shown);
  };
  return (
    <div className="relative">
      <input {...rest} type={shown ? "text" : "password"} className={cx(FIELD, "pr-9", className)} />
      <button
        type="button"
        onClick={toggle}
        disabled={busy}
        className="absolute top-1/2 right-2 -translate-y-1/2 rounded p-0.5 text-faint hover:text-text"
        title={shown ? "Hide password" : "Show password"}
        aria-label={shown ? "Hide password" : "Show password"}
      >
        {busy ? <Loader2 className="size-4 animate-spin" /> : shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select {...rest} className={cx(FIELD, "pr-8", className)}>
      {children}
    </select>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-faint">{hint}</span>}
    </label>
  );
}

/** Page tabs (underlined), e.g. Config Files and Settings. `dot` marks a tab, e.g. unsaved changes. */
export function Tabs<T extends string>({ value, tabs, onChange }: { value: T; tabs: { key: T; label: string; dot?: boolean }[]; onChange: (v: T) => void }) {
  return (
    <div className="mb-4 flex gap-1 border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={cx(
            "-mb-px border-b-2 px-4 py-2 text-[13px] font-medium transition-colors",
            value === t.key ? "border-accent text-text" : "border-transparent text-muted hover:text-text",
          )}
        >
          {t.label}
          {t.dot && <span className="ml-1.5 inline-block size-1.5 rounded-full bg-warn align-middle" title="Unsaved changes" />}
        </button>
      ))}
    </div>
  );
}

export function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { value: T; label: ReactNode }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-card-2 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "h-7 rounded-md px-3 text-xs font-medium transition-colors",
            value === o.value ? "bg-accent text-white" : "text-muted hover:text-text",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---- modal ------------------------------------------------------------------------

export function Modal({ open, title, onClose, children, footer, wide }: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose}>
      <div
        className={cx("w-full rounded-xl border border-line bg-card shadow-2xl", wide ? "max-w-4xl" : "max-w-md")}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="text-sm font-semibold">{title}</div>
          <button className="text-muted hover:text-text" onClick={onClose} aria-label="Close">
            <X className="size-4" />
          </button>
        </div>
        <div className="space-y-4 px-4 py-4">{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-line px-4 py-3">{footer}</div>}
      </div>
    </div>
  );
}

interface ConfirmOptions {
  title: string;
  body: ReactNode;
  confirm: string;
  danger?: boolean;
}

const ConfirmContext = createContext<(o: ConfirmOptions) => Promise<boolean>>(async () => false);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [opts, setOpts] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<(v: boolean) => void>(() => {});
  const ask = useCallback((o: ConfirmOptions) => {
    setOpts(o);
    return new Promise<boolean>((resolve) => (resolver.current = resolve));
  }, []);
  const close = (v: boolean) => {
    resolver.current(v);
    setOpts(null);
  };
  return (
    <ConfirmContext.Provider value={ask}>
      {children}
      <Modal
        open={!!opts}
        title={opts?.title ?? ""}
        onClose={() => close(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => close(false)}>Cancel</Button>
            <Button variant={opts?.danger ? "danger" : "primary"} onClick={() => close(true)} autoFocus>
              {opts?.confirm}
            </Button>
          </>
        }
      >
        <div className="text-[13px] leading-relaxed text-muted">{opts?.body}</div>
      </Modal>
    </ConfirmContext.Provider>
  );
}

export const useConfirm = () => useContext(ConfirmContext);

// ---- toasts -----------------------------------------------------------------------

interface Toast {
  id: number;
  tone: "ok" | "bad" | "accent";
  title: string;
  body?: string;
}

const ToastContext = createContext<(t: Omit<Toast, "id">) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((all) => [...all.slice(-3), { ...t, id }]);
    setTimeout(() => setToasts((all) => all.filter((x) => x.id !== id)), t.tone === "bad" ? 9000 : 4500);
  }, []);
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-96 max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className={cx("pointer-events-auto rounded-lg border bg-card px-3 py-2.5 shadow-xl", t.tone === "bad" ? "border-bad-line" : t.tone === "ok" ? "border-ok-line" : "border-line-strong")}>
            <div className={cx("flex items-center gap-2 text-[13px] font-medium", t.tone === "bad" ? "text-bad" : t.tone === "ok" ? "text-ok" : "text-text")}>
              {t.tone === "bad" ? <XCircle className="size-4" /> : t.tone === "ok" ? <CheckCircle2 className="size-4" /> : <Info className="size-4" />}
              {t.title}
            </div>
            {t.body && <div className="mt-1 whitespace-pre-wrap break-words pl-6 font-mono text-xs text-muted">{t.body}</div>}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
