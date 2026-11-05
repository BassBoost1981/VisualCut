import { Button, Card, Label, ListBox, Select } from "@heroui/react";
import type { Key } from "react-aria-components";
import { useHealth } from "../api/queries";
import type { Stage } from "../api/types";
import { LANGUAGES, useSettings, WHISPER_MODELS } from "../lib/settings";

const STAGES: { id: Stage; label: string }[] = [
  { id: "fusion", label: "Alles (bis Fusion)" },
  { id: "speech", label: "Bis Transkription" },
  { id: "technical", label: "Nur technische Analyse" },
  { id: "ingest", label: "Nur Ingest" },
];

function Choice({
  label,
  value,
  items,
  onChange,
}: {
  label: string;
  value: string;
  items: { id: string; label: string }[];
  onChange: (id: string) => void;
}) {
  return (
    <Select
      aria-label={label}
      selectedKey={value}
      onSelectionChange={(k: Key | null) => {
        if (k != null) onChange(String(k));
      }}
      className="w-full"
      fullWidth
    >
      <Label>{label}</Label>
      <Select.Trigger>
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox items={items}>
          {(item) => (
            <ListBox.Item id={item.id} textValue={item.label}>
              {item.label}
            </ListBox.Item>
          )}
        </ListBox>
      </Select.Popover>
    </Select>
  );
}

export function Settings() {
  const s = useSettings();
  const health = useHealth();
  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 p-6">
      <h1 className="text-base font-semibold">Einstellungen</h1>
      <Card className="flex flex-col gap-5 p-5">
        <Card.Header>
          <Card.Title>Analyse</Card.Title>
          <Card.Description>Werte, die an <code className="font-mono">POST /analyze</code> gehen. Lokal im Browser gespeichert.</Card.Description>
        </Card.Header>
        <Card.Content className="flex flex-col gap-4">
          <Choice label="Whisper-Modell" value={s.whisperModel} items={WHISPER_MODELS} onChange={s.setWhisperModel} />
          <Choice label="Sprache" value={s.language} items={LANGUAGES} onChange={s.setLanguage} />
          <Choice label="Stufen" value={s.stage} items={STAGES} onChange={(v) => s.setStage(v as Stage)} />
          <p className="text-xs text-text-faint">
            Fällt bei VRAM-Mangel automatisch auf medium (int8) zurück. Die Schwellen (Stille, Pausenlänge, Füllwörter) liegen in
            Phase 2 noch fest im Kern.
          </p>
        </Card.Content>
      </Card>
      <Card className="flex flex-col gap-3 p-5">
        <Card.Header>
          <Card.Title>Backend</Card.Title>
        </Card.Header>
        <Card.Content>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-text-muted">Status</dt>
            <dd>{health.data ? `erreichbar · Version ${health.data.version}` : "nicht erreichbar"}</dd>
            <dt className="text-text-muted">Frontend</dt>
            <dd>{health.data?.ui ? "wird vom Backend ausgeliefert (ui/dist)" : "Vite-Dev-Server mit Proxy"}</dd>
            <dt className="text-text-muted">Start</dt>
            <dd className="font-mono">visualcut serve</dd>
          </dl>
        </Card.Content>
        <Card.Footer>
          <Button
            variant="outline"
            size="sm"
            onPress={() => {
              s.setWhisperModel("large-v3");
              s.setLanguage("de");
              s.setStage("fusion");
            }}
          >
            Zurücksetzen
          </Button>
        </Card.Footer>
      </Card>
    </div>
  );
}
