import { useState } from "react";
import { Megaphone } from "lucide-react";
import { post, type ServiceKey } from "../lib/api";
import { useStatus } from "../lib/hooks";
import { ConsoleView } from "../components/ConsoleView";
import { StateBadge } from "../components/StateBadge";
import { Button, Input, PageHeader, Segmented, useToast } from "../components/ui";
import { GmCommandForm, GmReplies, useGmCommand } from "../components/GmCommand";

export function Console() {
  const { data: status } = useStatus();
  const [tab, setTab] = useState<ServiceKey>("world");
  const [message, setMessage] = useState("");
  const toast = useToast();
  const gm = useGmCommand();
  const world = status?.services.world;
  const worldReady = !!status?.commands.available;

  const announce = async (kind: "announce" | "notify") => {
    try {
      await post("/api/players/action", { action: kind, params: { message } });
      toast({ tone: "ok", title: kind === "announce" ? "Announcement sent" : "Notification sent" });
      setMessage("");
    } catch (e) {
      toast({ tone: "bad", title: "Could not send", body: (e as Error).message });
    }
  };

  const tabs: { value: ServiceKey; label: string }[] = [
    { value: "world", label: "Worldserver" },
    { value: "auth", label: "Authserver" },
    ...(status?.services.mysql.managed ? [{ value: "mysql" as ServiceKey, label: "MySQL" }] : []),
  ];

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Console"
        subtitle="Live server output. GM commands run on the Worldserver tab."
        right={status && <StateBadge state={status.services[tab].state} />}
      />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Segmented value={tab} options={tabs} onChange={setTab} />
        <form
          className="ml-auto flex min-w-80 flex-1 gap-2 xl:max-w-xl"
          onSubmit={(e) => {
            e.preventDefault();
            if (message.trim()) announce("announce");
          }}
        >
          <Input placeholder="Server-wide announcement…" value={message} onChange={(e) => setMessage(e.target.value)} disabled={!worldReady} />
          <Button type="submit" icon={<Megaphone className="size-4" />} disabled={!message.trim() || !worldReady}>
            Announce
          </Button>
          <Button type="button" variant="ghost" disabled={!message.trim() || !worldReady} onClick={() => announce("notify")}>
            Notify
          </Button>
        </form>
      </div>
      <div className="min-h-[420px] flex-1">
        <ConsoleView key={tab} service={tab} />
      </div>
      {tab === "world" && (
        <div className="mt-3 space-y-3">
          {/* Console replies show up in the output above; SOAP replies don't, so they are listed here. */}
          <GmReplies replies={gm.replies.filter((r) => r.via === "soap")} className="max-h-40" />
          <GmCommandForm gm={gm} disabled={!worldReady} placeholder={worldReady ? ".server info" : "Start the worldserver to run commands."} />
        </div>
      )}
      {tab === "world" && world?.state === "external" && (
        <p className="mt-2 text-xs text-muted">Worldserver was started outside the panel, so its console output isn't available here.</p>
      )}
    </div>
  );
}
