import { useState } from "react";
import { Shield } from "lucide-react";
import { post } from "../lib/api";
import { Button, Callout, Field, Input, PasswordInput } from "../components/ui";

export function Login({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    setBusy(true);
    try {
      await post("/api/auth/login", { username, password });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-3">
          <div className="flex size-12 items-center justify-center rounded-xl bg-accent-soft">
            <Shield className="size-6 text-accent" />
          </div>
          <div className="text-center">
            <h1 className="text-xl font-semibold">AzerothPanel</h1>
            <p className="mt-1 text-[13px] text-muted">Sign in to manage your server</p>
          </div>
        </div>
        <form
          className="space-y-4 rounded-xl border border-line bg-card p-5"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Field label="Username">
            <Input value={username} onChange={(e) => setUsername(e.target.value)} placeholder="admin" autoFocus autoComplete="username" />
          </Field>
          <Field label="Password">
            <PasswordInput value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
          </Field>
          {error && <Callout tone="bad">{error}</Callout>}
          <Button variant="primary" type="submit" className="w-full" loading={busy} disabled={!username || !password}>
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}

/** Shown after signing in with the default password: nothing else is usable until it's changed. */
export function ChangeDefaultPassword({ onDone }: { onDone: () => void }) {
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setError(null);
    if (next !== repeat) {
      setError("The passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await post("/api/auth/password", { current: "admin", new: next });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex h-full items-center justify-center p-6">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center gap-3">
          <div className="flex size-12 items-center justify-center rounded-xl bg-accent-soft">
            <Shield className="size-6 text-accent" />
          </div>
          <div className="text-center">
            <h1 className="text-xl font-semibold">Choose a new password</h1>
            <p className="mt-1 text-[13px] text-muted">You signed in with the default password. Set your own to continue.</p>
          </div>
        </div>
        <form
          className="space-y-4 rounded-xl border border-line bg-card p-5"
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
        >
          <Field label="New password" hint="At least 8 characters">
            <PasswordInput value={next} onChange={(e) => setNext(e.target.value)} autoFocus autoComplete="new-password" />
          </Field>
          <Field label="Repeat new password">
            <PasswordInput value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" />
          </Field>
          {error && <Callout tone="bad">{error}</Callout>}
          <Button variant="primary" type="submit" className="w-full" loading={busy} disabled={next.length < 8 || !repeat}>
            Save password
          </Button>
        </form>
      </div>
    </div>
  );
}
