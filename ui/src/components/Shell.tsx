import { Chip } from "@heroui/react";
import { useHealth } from "../api/queries";
import { href, type Route } from "../lib/router";
import { useSettings } from "../lib/settings";

const NAV: { label: string; screen: Route["screen"]; to: (lastHash: string | null) => Route | null }[] = [
  { label: "Start", screen: "start", to: () => ({ screen: "start" }) },
  { label: "Review", screen: "review", to: (h) => (h ? { screen: "review", hash: h } : null) },
  { label: "Export", screen: "export", to: (h) => (h ? { screen: "export", hash: h } : null) },
  { label: "Einstellungen", screen: "settings", to: () => ({ screen: "settings" }) },
];

export function Shell({ route, children }: { route: Route; children: React.ReactNode }) {
  const health = useHealth();
  const lastHash = useSettings((s) => s.lastHash);
  return (
    <div className="flex min-h-full flex-col">
      <header className="flex h-14 items-center gap-8 border-b border-line bg-panel-dark px-6">
        <div className="flex items-center gap-2.5 text-base font-bold tracking-tight">
          <img src="/logo.png" alt="" aria-hidden="true" width="26" height="26" />
          VisualCut
        </div>
        <nav aria-label="Hauptnavigation" className="flex gap-1">
          {NAV.map((item) => {
            const target = item.to(lastHash);
            const active = route.screen === item.screen || (item.screen === "start" && route.screen === "analyse");
            const cls = `rounded-[10px] px-3.5 py-2 ${active ? "bg-line font-semibold text-text" : "text-text-muted hover:text-text"} ${target ? "" : "pointer-events-none opacity-40"}`;
            return (
              <a key={item.label} href={target ? href(target) : "#"} className={cls} aria-current={active ? "page" : undefined}>
                {item.label}
              </a>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2.5">
          {health.data ? (
            <Chip color="success" variant="soft" size="sm">
              <span className="mr-1.5 inline-block h-1.5 w-1.5 rounded-full bg-[#17C964]" />
              visualcut serve · v{health.data.version}
            </Chip>
          ) : (
            <Chip color="danger" variant="soft" size="sm">
              Backend nicht erreichbar
            </Chip>
          )}
        </div>
      </header>
      <main className="flex min-h-0 flex-1 flex-col">{children}</main>
    </div>
  );
}
