import { useEffect, useState, type ReactNode } from "react";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Coins, Heart, LogOut, Mail, Megaphone, MicOff, Search, ShieldCheck, TrendingUp, Undo2, Users } from "lucide-react";
import { get, post, type CommandResult } from "../lib/api";
import { dateTime, duration, money } from "../lib/format";
import { CLASS_COLORS, GM_LEVELS } from "../lib/wow";
import { useStatus } from "../lib/hooks";
import { Badge, Button, Card, Empty, Field, Input, Modal, PageHeader, Segmented, Select, Spinner, useToast } from "../components/ui";

interface Character {
  guid: number;
  name: string;
  account: number;
  account_name: string | null;
  race_name: string;
  class: number;
  class_name: string;
  level: number;
  money: number;
  zone_name: string;
  online: number;
  totaltime: number;
  logout_time: number;
  banned: boolean;
  ban_reason: string | null;
}

interface Account {
  id: number;
  username: string;
  email: string;
  joindate: string;
  last_ip: string;
  last_login: string | null;
  online: number;
  gmlevel: number;
  banned: boolean;
  ban_reason: string | null;
  ban_until: number | null;
  muted: boolean;
  characters: number;
  totaltime: number;
}

type ActionKind = "kick" | "ban" | "unban" | "mute" | "unmute" | "gmlevel" | "level" | "revive" | "mail" | "money";
interface Pending {
  action: ActionKind;
  title: string;
  params: Record<string, string | number>;
}

function useDebounced<T>(value: T, ms = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function ActionDialog({ pending, onClose }: { pending: Pending | null; onClose: () => void }) {
  const [params, setParams] = useState<Record<string, string | number>>({});
  const [busy, setBusy] = useState(false);
  const toast = useToast();
  const qc = useQueryClient();
  useEffect(() => setParams(pending?.params ?? {}), [pending]);
  if (!pending) return null;
  const set = (k: string) => (e: { target: { value: string } }) => setParams((p) => ({ ...p, [k]: e.target.value }));
  const a = pending.action;

  const submit = async () => {
    setBusy(true);
    try {
      const body = { ...params };
      if (a === "money") body.copper = Math.round(Number(body.gold || 0) * 10000);
      const r = await post<CommandResult & { command: string }>("/api/players/action", { action: a, params: body });
      toast({ tone: r.ok ? "ok" : "bad", title: r.ok ? pending.title : `${pending.title} failed`, body: r.output || r.command });
      qc.invalidateQueries({ queryKey: ["players"] });
      onClose();
    } catch (e) {
      toast({ tone: "bad", title: `${pending.title} failed`, body: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open
      title={pending.title}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button variant={["ban", "kick", "mute"].includes(a) ? "danger" : "primary"} loading={busy} onClick={submit}>
            {pending.title.split(" ")[0]}
          </Button>
        </>
      }
    >
      {(a === "kick" || a === "ban" || a === "mute") && (
        <Field label="Reason">
          <Input value={params.reason ?? ""} onChange={set("reason")} placeholder="Shown to the player and stored with the ban" autoFocus />
        </Field>
      )}
      {a === "ban" && (
        <Field label="Duration" hint="Use units: 30m, 12h, 7d. Permanent bans use -1.">
          <Select value={params.duration ?? "1d"} onChange={set("duration")}>
            <option value="1h">1 hour</option>
            <option value="1d">1 day</option>
            <option value="7d">7 days</option>
            <option value="30d">30 days</option>
            <option value="-1">Permanent</option>
          </Select>
        </Field>
      )}
      {a === "mute" && (
        <Field label="Minutes">
          <Input type="number" min={1} value={params.minutes ?? 15} onChange={set("minutes")} />
        </Field>
      )}
      {a === "gmlevel" && (
        <Field label="GM level (all realms)">
          <Select value={params.level ?? 0} onChange={set("level")}>
            {GM_LEVELS.map((l, i) => (
              <option key={i} value={i}>{i} — {l}</option>
            ))}
          </Select>
        </Field>
      )}
      {a === "level" && (
        <Field label="New level">
          <Input type="number" min={1} max={255} value={params.level ?? 80} onChange={set("level")} autoFocus />
        </Field>
      )}
      {(a === "mail" || a === "money") && (
        <>
          <Field label="Subject">
            <Input value={params.subject ?? ""} onChange={set("subject")} autoFocus />
          </Field>
          <Field label="Message">
            <Input value={params.text ?? ""} onChange={set("text")} />
          </Field>
        </>
      )}
      {a === "money" && (
        <Field label="Gold">
          <Input type="number" min={0} step="0.01" value={params.gold ?? 10} onChange={set("gold")} />
        </Field>
      )}
      {(a === "unban" || a === "unmute" || a === "revive") && (
        <p className="text-[13px] text-muted">This runs the GM command on the worldserver console.</p>
      )}
    </Modal>
  );
}

function CharactersTable({ search, onlineOnly, act }: { search: string; onlineOnly: boolean; act: (p: Pending) => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["players", "characters", search, onlineOnly],
    queryFn: () => get<{ total: number; items: Character[] }>(`/api/players/characters?search=${encodeURIComponent(search)}&online=${onlineOnly}&limit=200`),
    refetchInterval: 5000,
    placeholderData: keepPreviousData,
  });
  if (isLoading) return <div className="p-6"><Spinner /></div>;
  if (error) return <Empty title="Couldn't load characters">{(error as Error).message}</Empty>;
  if (!data?.items.length) return <Empty icon={<Users className="size-6" />} title={onlineOnly ? "Nobody is online" : "No characters found"} />;
  return (
    <>
      <div className="px-4 pt-3 text-xs text-muted">{data.total} shown</div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line text-left">
              {["Name", "Account", "Race", "Class", "Level", "Zone", "Gold", "Played", "Status", "Actions"].map((h) => (
                <th key={h} className="label-caps px-4 py-2.5 !text-[10.5px]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.items.map((c) => (
              <tr key={c.guid} className="border-b border-line whitespace-nowrap last:border-0 hover:bg-card-2">
                <td className="px-4 py-2.5 font-medium">{c.name}</td>
                <td className="px-4 py-2.5 text-muted">{c.account_name ?? c.account}</td>
                <td className="px-4 py-2.5 text-muted">{c.race_name}</td>
                <td className="px-4 py-2.5" style={{ color: c.class === 5 ? "var(--text)" : CLASS_COLORS[c.class] }}>{c.class_name}</td>
                <td className="px-4 py-2.5 font-mono">{c.level}</td>
                <td className="px-4 py-2.5 text-muted">{c.zone_name}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{money(c.money)}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{duration(c.totaltime)}</td>
                <td className="px-4 py-2.5">
                  <div className="flex gap-1">
                    {c.online ? <Badge tone="ok" dot>Online</Badge> : <Badge tone="muted">Offline</Badge>}
                    {c.banned && <Badge tone="bad">Banned</Badge>}
                  </div>
                </td>
                <td className="px-4 py-2">
                  <div className="flex gap-1">
                    {!!c.online && (
                      <Button size="sm" variant="danger" icon={<LogOut className="size-3" />} onClick={() => act({ action: "kick", title: `Kick ${c.name}`, params: { name: c.name } })}>
                        Kick
                      </Button>
                    )}
                    <IconAction title="Ban character" icon={<Ban className="size-3.5" />} onClick={() => act(c.banned ? { action: "unban", title: `Unban ${c.name}`, params: { type: "character", target: c.name } } : { action: "ban", title: `Ban ${c.name}`, params: { type: "character", target: c.name, duration: "1d" } })} />
                    <IconAction title="Mute" icon={<MicOff className="size-3.5" />} onClick={() => act({ action: "mute", title: `Mute ${c.name}`, params: { name: c.name, minutes: 15 } })} />
                    <IconAction title="Set level" icon={<TrendingUp className="size-3.5" />} onClick={() => act({ action: "level", title: `Set level of ${c.name}`, params: { name: c.name, level: c.level } })} />
                    <IconAction title="Send mail" icon={<Mail className="size-3.5" />} onClick={() => act({ action: "mail", title: `Mail ${c.name}`, params: { name: c.name } })} />
                    <IconAction title="Send gold" icon={<Coins className="size-3.5" />} onClick={() => act({ action: "money", title: `Send gold to ${c.name}`, params: { name: c.name, subject: "Gift" } })} />
                    <IconAction title="Revive" icon={<Heart className="size-3.5" />} onClick={() => act({ action: "revive", title: `Revive ${c.name}`, params: { name: c.name } })} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function IconAction({ title, icon, onClick }: { title: string; icon: ReactNode; onClick: () => void }) {
  return (
    <button title={title} onClick={onClick} className="flex size-7 items-center justify-center rounded-md border border-line text-muted hover:border-line-strong hover:text-text">
      {icon}
    </button>
  );
}

function AccountsTable({ search, act }: { search: string; act: (p: Pending) => void }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["players", "accounts", search],
    queryFn: () => get<{ total: number; items: Account[] }>(`/api/players/accounts?search=${encodeURIComponent(search)}&limit=200`),
    placeholderData: keepPreviousData,
  });
  if (isLoading) return <div className="p-6"><Spinner /></div>;
  if (error) return <Empty title="Couldn't load accounts">{(error as Error).message}</Empty>;
  if (!data?.items.length) return <Empty icon={<Users className="size-6" />} title="No accounts found" />;
  return (
    <>
      <div className="px-4 pt-3 text-xs text-muted">{data.total} shown</div>
      <div className="overflow-x-auto">
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-line text-left">
              {["ID", "Username", "GM level", "Characters", "Last login", "Last IP", "Joined", "Status", "Actions"].map((h) => (
                <th key={h} className="label-caps px-4 py-2.5 !text-[10.5px]">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.items.map((a) => (
              <tr key={a.id} className="border-b border-line whitespace-nowrap last:border-0 hover:bg-card-2">
                <td className="px-4 py-2.5 font-mono text-muted">{a.id}</td>
                <td className="px-4 py-2.5 font-medium">{a.username}</td>
                <td className="px-4 py-2.5">{a.gmlevel > 0 ? <Badge tone="accent">{GM_LEVELS[a.gmlevel] ?? a.gmlevel}</Badge> : <span className="text-muted">Player</span>}</td>
                <td className="px-4 py-2.5 font-mono">{a.characters}</td>
                <td className="px-4 py-2.5 text-muted">{dateTime(a.last_login)}</td>
                <td className="px-4 py-2.5 font-mono text-xs text-muted">{a.last_ip}</td>
                <td className="px-4 py-2.5 text-muted">{dateTime(a.joindate)}</td>
                <td className="px-4 py-2.5">
                  <div className="flex gap-1">
                    {a.online ? <Badge tone="ok" dot>Online</Badge> : <Badge tone="muted">Offline</Badge>}
                    {a.banned && <Badge tone="bad">{a.ban_until ? `Banned until ${dateTime(a.ban_until)}` : "Banned"}</Badge>}
                    {a.muted && <Badge tone="warn">Muted</Badge>}
                  </div>
                </td>
                <td className="px-4 py-2">
                  <div className="flex gap-1">
                    {a.banned ? (
                      <Button size="sm" icon={<Undo2 className="size-3" />} onClick={() => act({ action: "unban", title: `Unban ${a.username}`, params: { type: "account", target: a.username } })}>
                        Unban
                      </Button>
                    ) : (
                      <Button size="sm" variant="danger" icon={<Ban className="size-3" />} onClick={() => act({ action: "ban", title: `Ban ${a.username}`, params: { type: "account", target: a.username, duration: "1d" } })}>
                        Ban
                      </Button>
                    )}
                    <Button size="sm" icon={<ShieldCheck className="size-3" />} onClick={() => act({ action: "gmlevel", title: `Set GM level of ${a.username}`, params: { account: a.username, level: a.gmlevel } })}>
                      GM level
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function Players() {
  const [tab, setTab] = useState<"characters" | "accounts">("characters");
  const [query, setQuery] = useState("");
  const [onlineOnly, setOnlineOnly] = useState(false);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const search = useDebounced(query.trim());
  const toast = useToast();
  const { data: status } = useStatus();
  const worldReady = !!status?.commands.available;

  const act = (p: Pending) => {
    if (!worldReady) {
      toast({ tone: "bad", title: "Worldserver isn't available", body: "Player actions run as GM commands: start the worldserver from the panel, or set up SOAP in Settings." });
      return;
    }
    setPending(p);
  };

  const announce = async () => {
    try {
      await post("/api/players/action", { action: "announce", params: { message } });
      toast({ tone: "ok", title: "Announcement sent" });
      setMessage("");
    } catch (e) {
      toast({ tone: "bad", title: "Could not send", body: (e as Error).message });
    }
  };

  return (
    <>
      <PageHeader title="Players" subtitle="View characters, manage accounts and send announcements" />
      <Card className="mb-4 flex flex-wrap items-center gap-3 p-3">
        <Segmented value={tab} onChange={setTab} options={[{ value: "characters", label: "Characters" }, { value: "accounts", label: "Accounts" }]} />
        <div className="relative w-72">
          <Search className="absolute top-2.5 left-3 size-4 text-faint" />
          <Input className="pl-9" placeholder={`Search ${tab}…`} value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        {tab === "characters" && (
          <label className="flex items-center gap-2 text-[13px] text-muted">
            <input type="checkbox" checked={onlineOnly} onChange={(e) => setOnlineOnly(e.target.checked)} className="accent-[var(--accent)]" />
            Online only
          </label>
        )}
      </Card>
      <Card className="mb-4 p-3">
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (message.trim()) announce();
          }}
        >
          <div className="relative flex-1">
            <Megaphone className="absolute top-2.5 left-3 size-4 text-faint" />
            <Input className="pl-9" placeholder="Server-wide announcement…" value={message} onChange={(e) => setMessage(e.target.value)} disabled={!worldReady} />
          </div>
          <Button type="submit" disabled={!message.trim() || !worldReady}>Announce</Button>
        </form>
      </Card>
      <Card>
        <div className="border-b border-line px-4 py-3 text-[13px] font-semibold">{tab === "characters" ? "Characters" : "Accounts"}</div>
        {tab === "characters" ? <CharactersTable search={search} onlineOnly={onlineOnly} act={act} /> : <AccountsTable search={search} act={act} />}
      </Card>
      <ActionDialog pending={pending} onClose={() => setPending(null)} />
    </>
  );
}
