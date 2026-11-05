import { Alert, Button, Card, Chip, Input, ListBox, Select, Spinner } from "@heroui/react";
import { useEffect, useState } from "react";
import type { Key } from "react-aria-components";
import { useCatalog, useSaveCatalog } from "../api/queries";
import type { EventCatalog, EventDefinition, EventEffect } from "../api/types";
import { EFFECTS, typeFromPrompt } from "../lib/events";

function EffectSelect({ value, onChange, label }: { value: EventEffect; onChange: (v: EventEffect) => void; label: string }) {
  return (
    <Select
      aria-label={label}
      selectedKey={value}
      onSelectionChange={(k: Key | null) => {
        if (k != null) onChange(String(k) as EventEffect);
      }}
      className="w-32"
    >
      <Select.Trigger>
        <Select.Value />
        <Select.Indicator />
      </Select.Trigger>
      <Select.Popover>
        <ListBox items={EFFECTS}>
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

/**
 * Editor für events.yaml (globale Datei): Prompt für X-CLIP, Audio-Prompt für CLAP, Anzeigename und Wirkung pro
 * Eintrag, dazu das Vision-LLM-Budget. Eine Projektdatei .visualcut/<hash>/events.yaml hat bei der Analyse Vorrang.
 */
export function EventsEditor() {
  const query = useCatalog();
  const save = useSaveCatalog();
  const [draft, setDraft] = useState<EventCatalog | null>(null);
  const [newPrompt, setNewPrompt] = useState("");

  useEffect(() => {
    if (query.data && draft === null) setDraft(structuredClone(query.data.catalog));
  }, [query.data, draft]);

  const dirty = draft !== null && query.data !== undefined && JSON.stringify(draft) !== JSON.stringify(query.data.catalog);
  const events = draft?.events ?? [];
  const update = (i: number, patch: Partial<EventDefinition>) =>
    setDraft((d) => (d ? { ...d, events: (d.events ?? []).map((e, k) => (k === i ? { ...e, ...patch } : e)) } : d));
  const remove = (i: number) => setDraft((d) => (d ? { ...d, events: (d.events ?? []).filter((_, k) => k !== i) } : d));
  const add = () => {
    const prompt = newPrompt.trim();
    if (!prompt || !draft) return;
    const type = typeFromPrompt(prompt, new Set(events.map((e) => e.type)));
    setDraft({ ...draft, events: [...events, { type, label: type.replace(/_/g, " "), prompt, effect: "marker" }] });
    setNewPrompt("");
  };

  return (
    <Card className="flex flex-col gap-4 p-5" id="ereignisse">
      <Card.Header>
        <Card.Title>Ereignisse</Card.Title>
        <Card.Description>
          events.yaml · Textbeschreibungen für X-CLIP (Bild) und CLAP (Ton), frei erweiterbar. Neue Prompts wirken bei der
          nächsten Analyse, Anzeigename und Wirkung sofort.
        </Card.Description>
      </Card.Header>
      <Card.Content className="flex flex-col gap-3">
        {query.isLoading && <Spinner size="sm" />}
        {query.error && (
          <Alert status="danger">
            <Alert.Content>
              <Alert.Title>events.yaml nicht lesbar</Alert.Title>
              <Alert.Description>{query.error.message}</Alert.Description>
            </Alert.Content>
          </Alert>
        )}
        {draft && (
          <>
            <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,0.9fr)_auto_auto] items-center gap-2 text-xs text-text-muted">
              <span>Bild-Prompt (X-CLIP)</span>
              <span>Ton-Prompt (CLAP)</span>
              <span>Anzeige</span>
              <span>Wirkung</span>
              <span />
              {events.map((e, i) => (
                <div key={`${e.type}-${i}`} className="contents" aria-label={`Ereignis ${e.type}`}>
                  <Input
                    aria-label={`Bild-Prompt ${e.type}`}
                    value={e.prompt ?? ""}
                    placeholder="kein Bild-Prompt"
                    onChange={(ev) => update(i, { prompt: ev.target.value })}
                    className="font-mono text-xs"
                  />
                  <Input
                    aria-label={`Ton-Prompt ${e.type}`}
                    value={e.audio_prompt ?? ""}
                    placeholder="kein Ton-Prompt"
                    onChange={(ev) => update(i, { audio_prompt: ev.target.value })}
                    className="font-mono text-xs"
                  />
                  {e.background ? (
                    <Chip size="sm" variant="soft" title="Nur Vergleichsklasse, erzeugt kein Event">
                      Vergleich: {e.label}
                    </Chip>
                  ) : (
                    <Input aria-label={`Anzeigename ${e.type}`} value={e.label} onChange={(ev) => update(i, { label: ev.target.value })} />
                  )}
                  {e.background ? (
                    <span className="w-32 text-text-faint">kein Event</span>
                  ) : (
                    <EffectSelect label={`Wirkung ${e.type}`} value={e.effect ?? "marker"} onChange={(v) => update(i, { effect: v })} />
                  )}
                  <Button size="sm" variant="ghost" isIconOnly aria-label={`${e.type} entfernen`} onPress={() => remove(i)}>
                    ×
                  </Button>
                </div>
              ))}
            </div>
            <div className="flex gap-2">
              <Input
                aria-label="Neue Aktion"
                value={newPrompt}
                placeholder="Neue Aktion auf Englisch, z. B. person drinking coffee"
                onChange={(ev) => setNewPrompt(ev.target.value)}
                onKeyDown={(ev) => {
                  if (ev.key === "Enter") add();
                }}
                className="flex-1"
              />
              <Button variant="secondary" onPress={add} isDisabled={!newPrompt.trim()}>
                Hinzufügen
              </Button>
            </div>
            <label className="flex flex-wrap items-center gap-3 text-sm">
              <span className="flex flex-col">
                <span>Vision-LLM-Budget pro Video</span>
                <span className="text-xs text-text-faint">Nur für unklare Fälle (Ebene C), ohne API-Key beurteilt der Agent.</span>
              </span>
              <input
                type="range"
                min={0}
                max={100}
                value={draft.vision_budget ?? 40}
                aria-label="Vision-Budget"
                onChange={(ev) => setDraft({ ...draft, vision_budget: Number(ev.target.value) })}
                className="ml-auto w-48 accent-[#338EF7]"
              />
              <span className="w-24 font-mono text-xs">{draft.vision_budget ?? 40} Aufrufe</span>
            </label>
          </>
        )}
        {save.error && <div className="text-xs text-[#F31260]">Speichern fehlgeschlagen: {save.error.message}</div>}
      </Card.Content>
      <Card.Footer className="flex items-center gap-3">
        <Button variant="primary" size="sm" isDisabled={!dirty || save.isPending} onPress={() => draft && save.mutate(draft)}>
          Speichern
        </Button>
        <Button variant="outline" size="sm" isDisabled={!dirty} onPress={() => query.data && setDraft(structuredClone(query.data.catalog))}>
          Verwerfen
        </Button>
        {query.data && (
          <span className="truncate font-mono text-[11px] text-text-faint" title={query.data.path}>
            {query.data.path}
          </span>
        )}
      </Card.Footer>
    </Card>
  );
}
