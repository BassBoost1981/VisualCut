import { Button, Chip, ProgressBar } from "@heroui/react";
import type { Cut, CutStatus, Word } from "../api/types";
import { fmtSeconds, fmtTimecode } from "../lib/format";
import { REASON_COLOR, REASON_LABEL, STATUS_COLOR, STATUS_LABEL } from "../lib/reasons";

interface Props {
  cut: Cut | null;
  words: Word[];
  fps: number;
  onDecide: (status: CutStatus) => void;
  onJump: () => void;
  pending: boolean;
  /** Nur für manuelle Cuts: aus manual.json löschen */
  onDelete: () => void;
}

const SOURCE_LABEL = { rule: "Regel", llm: "LLM", manual: "manuell" };

export function CutPanel({ cut, words, fps, onDecide, onJump, pending, onDelete }: Props) {
  if (!cut) {
    return (
      <section aria-label="Ausgewählter Cut" className="rounded-2xl border border-line bg-panel px-5 py-4 text-sm text-text-muted">
        Kein Cut ausgewählt. Klick auf einen Cut in der Timeline oder im Transkript, oder <kbd className="font-mono">↓</kbd> für den nächsten.
      </section>
    );
  }
  const color = REASON_COLOR[cut.reason];
  const status = cut.status ?? "open";
  const text = words
    .filter((w) => w.id >= cut.start_word && w.id <= cut.end_word)
    .map((w) => w.text)
    .join(" ");
  const start = cut.start ?? 0;
  const end = cut.end ?? 0;
  return (
    <section aria-label="Ausgewählter Cut" className="flex flex-wrap items-start gap-5 rounded-2xl border border-line bg-panel px-5 py-4">
      <div className="flex min-w-0 flex-1 basis-80 flex-col gap-2.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="rounded-full px-2.5 py-1 text-xs font-semibold text-[#09090b]" style={{ background: color }}>
            {REASON_LABEL[cut.reason]}
          </span>
          <button type="button" onClick={onJump} className="font-mono text-[13px] hover:underline" title="Zum Cut springen">
            {fmtTimecode(start, fps)} → {fmtTimecode(end, fps)}
          </button>
          <span className="text-xs text-text-muted">
            {fmtSeconds(end - start)} · Wort {cut.start_word} bis {cut.end_word}
            {cut.start_frame != null && cut.end_frame != null && ` · Frame ${cut.start_frame}–${cut.end_frame}`}
          </span>
          <Chip size="sm" variant="soft" className="ml-auto" style={{ color: STATUS_COLOR[status] }}>
            {STATUS_LABEL[status]}
          </Chip>
        </div>
        <p className="m-0 leading-relaxed">
          <span className="rounded px-1" style={{ background: `${color}22`, color }}>
            {text || "…"}
          </span>
        </p>
        <div className="flex flex-wrap gap-4 text-xs text-text-muted">
          <span>
            Quelle: <span className="text-text">{SOURCE_LABEL[cut.source ?? "rule"]}</span>
          </span>
          {cut.maybe && (
            <span>
              <span className="text-[#F5A524]">maybe</span> · Konfidenz unter 0,6
            </span>
          )}
          {cut.note && (
            <span>
              Notiz: <span className="text-text">{cut.note}</span>
            </span>
          )}
          <span className="font-mono text-text-faint">{cut.id}</span>
        </div>
      </div>
      <div className="flex basis-56 flex-col gap-2">
        <div className="flex justify-between text-xs text-text-muted">
          <span>Konfidenz</span>
          <span className="font-semibold text-text">{cut.confidence.toFixed(2)}</span>
        </div>
        <ProgressBar aria-label="Konfidenz" value={cut.confidence} maxValue={1} size="sm" color={cut.confidence >= 0.8 ? "success" : cut.confidence >= 0.6 ? "warning" : "danger"}>
          <ProgressBar.Track>
            <ProgressBar.Fill />
          </ProgressBar.Track>
        </ProgressBar>
        <div className="mt-1.5 flex gap-2">
          <Button
            className="flex-1 bg-[#17C964] text-[#052e16]"
            variant="primary"
            onPress={() => onDecide("accepted")}
            isDisabled={pending || status === "accepted"}
          >
            Annehmen
          </Button>
          <Button className="flex-1" variant="outline" onPress={() => onDecide("rejected")} isDisabled={pending || status === "rejected"}>
            Verwerfen
          </Button>
        </div>
        <Button variant="ghost" size="sm" onPress={() => onDecide("open")} isDisabled={pending || status === "open"}>
          Wieder öffnen
        </Button>
        {cut.source === "manual" && (
          <Button variant="danger-soft" size="sm" onPress={onDelete} isDisabled={pending}>
            Manuellen Cut löschen (Entf)
          </Button>
        )}
      </div>
    </section>
  );
}
