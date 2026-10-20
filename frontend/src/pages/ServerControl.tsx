import { Play, Power, RotateCw, Send, Skull, Square } from "lucide-react";
import type { ServiceKey, ServiceStatus, Status } from "../lib/api";
import { useServerActions, useStatus } from "../lib/hooks";
import { isUp } from "../components/StateBadge";
import { Button, Callout, Card, PageHeader, Spinner } from "../components/ui";
import { ServiceDetailCard } from "../components/ServiceDetailCard";
import { GmCommandForm, GmReplies, useGmCommand } from "../components/GmCommand";

function Controls({ s }: { s: ServiceStatus }) {
  const actions = useServerActions();
  const busy = s.state === "starting" || s.state === "stopping";
  const up = isUp(s.state);
  return (
    <div className="mt-4 flex flex-wrap gap-2">
      <Button size="sm" variant="success" icon={<Play className="size-3.5" />} disabled={up || busy} onClick={() => actions.start(s.key, s.label)}>
        Start
      </Button>
      <Button size="sm" variant="danger" icon={<Square className="size-3.5" />} disabled={!up && s.state !== "starting"} onClick={() => actions.stop(s.key, s.label)}>
        Stop
      </Button>
      <Button size="sm" icon={<RotateCw className="size-3.5" />} disabled={!up} onClick={() => actions.restart(s.key, s.label)}>
        Restart
      </Button>
      {(up || busy) && (
        <Button size="sm" variant="ghost" className="ml-auto" icon={<Skull className="size-3.5" />} onClick={() => actions.kill(s.key, s.label)}>
          Force kill
        </Button>
      )}
    </div>
  );
}

function GmConsole({ world, commands }: { world: ServiceStatus; commands: Status["commands"] }) {
  const gm = useGmCommand();
  const usable = commands.available;

  return (
    <div className="mt-4 border-t border-line pt-4">
      <div className="mb-2 flex items-center gap-1.5 text-xs text-muted">
        <Send className="size-3.5" /> GM console
        {usable && <span className="ml-auto text-faint">via {commands.soap ? "SOAP" : "console"}</span>}
      </div>
      {!usable && (
        <div className="mb-2">
          <Callout tone="warn">
            {world.state === "external"
              ? "Worldserver was started outside the panel. Set up SOAP in Settings, or start it from here, to run commands."
              : "Start the worldserver to run commands."}
          </Callout>
        </div>
      )}
      <GmCommandForm gm={gm} disabled={!usable} />
      <GmReplies replies={gm.replies} className="mt-3 max-h-72" />
    </div>
  );
}

export function ServerControl() {
  const { data: status } = useStatus();
  const actions = useServerActions();
  if (!status) return <Spinner />;
  const order: ServiceKey[] = status.services.mysql.managed ? ["mysql", "auth", "world"] : ["auth", "world"];

  return (
    <>
      <PageHeader
        title="Server Control"
        subtitle="Start, stop and restart server processes, and send GM commands"
        right={
          <>
            <Button variant="success" icon={<Play className="size-4" />} onClick={actions.startAll} disabled={!!status.job}>
              Start all
            </Button>
            <Button variant="danger" icon={<Power className="size-4" />} onClick={actions.stopAll} disabled={!!status.job}>
              Safe stop all
            </Button>
          </>
        }
      />
      <div className="mb-4">
        <Callout tone="accent">
          Stops are always graceful: Worldserver runs <code className="font-mono">server shutdown</code> with a countdown (players are saved), Authserver
          and MySQL receive Ctrl-C. MySQL can't be stopped while Authserver or Worldserver are connected to it.
        </Callout>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        {order.map((key) => {
          const s = status.services[key];
          return (
            <ServiceDetailCard key={key} s={s}>
              <Controls s={s} />
              {key === "world" && <GmConsole world={s} commands={status.commands} />}
            </ServiceDetailCard>
          );
        })}
      </div>
      {!status.services.mysql.managed && (
        <Card className="mt-4 p-4 text-xs text-muted">
          MySQL isn't managed by the panel: no MySQL folder is chosen. Extract the MySQL ZIP and choose its folder on Setup → Requirements, or start your own MySQL yourself.
        </Card>
      )}
    </>
  );
}
