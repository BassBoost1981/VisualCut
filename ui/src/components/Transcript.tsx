import { Label, Switch } from "@heroui/react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useEffect, useMemo, useRef, useState } from "react";
import { useHotkeys } from "react-hotkeys-hook";
import type { Cut, CutReason, Word } from "../api/types";
import { fmtDuration } from "../lib/format";
import { REASON_COLOR, REASON_LABEL, REASONS } from "../lib/reasons";
import { DEFAULT_MANUAL_REASON, MANUAL_REASONS, rangeText, wordIdAt, wordRange, type WordRange } from "../lib/manual";
import { useReview } from "../lib/review-store";

interface Props {
  words: Word[];
  cuts: Cut[];
  currentTime: number;
  onSeek: (t: number) => void;
  /** Markierte Wortspanne als manuellen Cut speichern */
  onMark: (range: WordRange, reason: CutReason) => void;
  markPending: boolean;
  markError: string | null;
}

interface Row {
  start: number;
  words: Word[];
}

const GAP_S = 1.0;
const MAX_WORDS = 40;

/** Transkript als virtualisierte Absätze. Wörter in Cuts sind nach Grund eingefärbt, das aktuelle Wort läuft mit. */
export function Transcript({ words, cuts, currentTime, onSeek, onMark, markPending, markError }: Props) {
  const parentRef = useRef<HTMLDivElement>(null);
  const { selectedCutId, select, follow, setFollow, reasonFilter, setReasonFilter, onlyOpen, setOnlyOpen, onlyMaybe, setOnlyMaybe, marked, setMarked } = useReview();
  const anchorRef = useRef<number | null>(null); // letztes angeklicktes Wort, Startpunkt für Shift-Klick
  const draggedRef = useRef(false); // der folgende Klick gehört zu einer Zieh-Markierung
  const [markReason, setMarkReason] = useState<CutReason>(DEFAULT_MANUAL_REASON);

  // Markierung per Ziehen: native Textauswahl auf Wort-IDs abbilden, dann die eigene Hervorhebung zeigen
  const onMouseUp = () => {
    const sel = window.getSelection();
    if (!sel || sel.isCollapsed) return;
    const a = wordIdAt(sel.anchorNode);
    const b = wordIdAt(sel.focusNode);
    sel.removeAllRanges();
    if (a != null && b != null) {
      draggedRef.current = true;
      setMarked(wordRange(a, b));
    }
  };
  const save = () => {
    if (marked && !markPending) onMark(marked, markReason);
  };
  const opts = { preventDefault: true, enableOnFormTags: false };
  useHotkeys("x", save, opts, [marked, markReason, markPending, onMark]);
  useHotkeys("escape", () => setMarked(null), { enableOnFormTags: true }, [setMarked]);

  const rows = useMemo<Row[]>(() => {
    const out: Row[] = [];
    let cur: Word[] = [];
    for (const w of words) {
      const prev = cur[cur.length - 1];
      if (cur.length && (w.start - prev.end > GAP_S || cur.length >= MAX_WORDS)) {
        out.push({ start: cur[0].start, words: cur });
        cur = [];
      }
      cur.push(w);
    }
    if (cur.length) out.push({ start: cur[0].start, words: cur });
    return out;
  }, [words]);

  // Wort-ID -> Cut (für Färbung); bei Überlappung gewinnt der erste
  const cutByWord = useMemo(() => {
    const m = new Map<number, Cut>();
    for (const c of cuts) for (let i = c.start_word; i <= c.end_word; i++) if (!m.has(i)) m.set(i, c);
    return m;
  }, [cuts]);

  const currentWordId = useMemo(() => {
    let lo = 0;
    let hi = words.length - 1;
    let best = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (words[mid].start <= currentTime) {
        best = mid;
        lo = mid + 1;
      } else hi = mid - 1;
    }
    return best >= 0 && words[best].end + 0.3 >= currentTime ? words[best].id : -1;
  }, [words, currentTime]);

  const rowOfWord = useMemo(() => {
    const m = new Map<number, number>();
    rows.forEach((r, i) => r.words.forEach((w) => m.set(w.id, i)));
    return m;
  }, [rows]);

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 96,
    overscan: 6,
  });

  useEffect(() => {
    if (!follow || currentWordId < 0) return;
    const row = rowOfWord.get(currentWordId);
    if (row != null) virtualizer.scrollToIndex(row, { align: "center", behavior: "smooth" });
  }, [currentWordId, follow, rowOfWord, virtualizer]);

  useEffect(() => {
    if (!selectedCutId) return;
    const cut = cuts.find((c) => c.id === selectedCutId);
    if (!cut) return;
    const row = rowOfWord.get(cut.start_word);
    if (row != null) virtualizer.scrollToIndex(row, { align: "center" });
  }, [selectedCutId, cuts, rowOfWord, virtualizer]);

  const counts = useMemo(() => {
    const by = new Map<CutReason, number>();
    for (const c of cuts) by.set(c.reason, (by.get(c.reason) ?? 0) + 1);
    return by;
  }, [cuts]);
  const openCount = cuts.filter((c) => c.status === "open").length;
  const maybeCount = cuts.filter((c) => c.maybe).length;

  const chip = (active: boolean, color?: string) =>
    `rounded-full border px-2.5 py-1 text-xs transition-colors ${active ? "border-primary bg-[#0b2447] text-text" : "border-line-light text-text-muted hover:text-text"}` +
    (color && active ? "" : "");

  return (
    <aside aria-label="Transkript" className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-line bg-panel">
      <div className="flex flex-col gap-2.5 border-b border-line px-4 pb-2.5 pt-3.5">
        <div className="flex flex-wrap items-center gap-2.5">
          <div className="font-semibold">Transkript</div>
          <span className="text-xs text-text-muted">{words.length.toLocaleString("de-DE")} Wörter</span>
          <Switch isSelected={follow} onChange={setFollow} size="sm" className="ml-auto">
            <Switch.Content>
              <Switch.Control>
                <Switch.Thumb />
              </Switch.Control>
              <Label className="text-xs text-text-muted">mitlaufen</Label>
            </Switch.Content>
          </Switch>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <button type="button" className={chip(!reasonFilter && !onlyOpen && !onlyMaybe)} onClick={() => { setReasonFilter(null); setOnlyOpen(false); setOnlyMaybe(false); }}>
            Alle {cuts.length}
          </button>
          {REASONS.filter((r) => counts.has(r)).map((r) => (
            <button
              key={r}
              type="button"
              className={chip(reasonFilter === r)}
              style={reasonFilter === r ? { borderColor: REASON_COLOR[r], background: "transparent", color: REASON_COLOR[r] } : undefined}
              onClick={() => setReasonFilter(reasonFilter === r ? null : r)}
            >
              <span className="mr-1 inline-block h-2 w-2 rounded-sm align-middle" style={{ background: REASON_COLOR[r] }} />
              {REASON_LABEL[r]} {counts.get(r)}
            </button>
          ))}
          <button type="button" className={chip(onlyOpen)} onClick={() => setOnlyOpen(!onlyOpen)}>
            nur offen {openCount}
          </button>
          <button type="button" className={chip(onlyMaybe)} onClick={() => setOnlyMaybe(!onlyMaybe)}>
            nur maybe {maybeCount}
          </button>
        </div>
      </div>

      <div ref={parentRef} className="min-h-0 flex-1 overflow-auto px-4 py-3" onMouseDown={() => (draggedRef.current = false)} onMouseUp={onMouseUp}>
        {words.length === 0 && <p className="text-sm text-text-muted">Kein Transkript (Stufe 2 fehlt oder keine Tonspur).</p>}
        <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
          {virtualizer.getVirtualItems().map((item) => {
            const row = rows[item.index];
            return (
              <div
                key={item.key}
                ref={virtualizer.measureElement}
                data-index={item.index}
                className="absolute left-0 top-0 w-full pb-3.5"
                style={{ transform: `translateY(${item.start}px)` }}
              >
                <div className="mb-0.5 font-mono text-[11px] text-text-faint">{fmtDuration(row.start)}</div>
                <p className="m-0 text-sm leading-7">
                  {row.words.map((w) => {
                    const cut = cutByWord.get(w.id);
                    const isCurrent = w.id === currentWordId;
                    const isSelected = cut && cut.id === selectedCutId;
                    const color = cut ? REASON_COLOR[cut.reason] : undefined;
                    const rejected = cut?.status === "rejected";
                    const open = cut?.status === "open";
                    const isMarked = marked != null && w.id >= marked[0] && w.id <= marked[1];
                    return (
                      <span
                        key={w.id}
                        role="button"
                        tabIndex={-1}
                        data-word-id={w.id}
                        onClick={(e) => {
                          if (e.shiftKey && anchorRef.current != null) {
                            setMarked(wordRange(anchorRef.current, w.id));
                            return;
                          }
                          if (draggedRef.current) {
                            draggedRef.current = false;
                            return;
                          }
                          anchorRef.current = w.id;
                          setMarked(null);
                          onSeek(w.start);
                          if (cut) select(cut.id);
                        }}
                        className={`cursor-pointer rounded px-0.5 ${isCurrent ? "bg-[#0b2447] font-semibold text-text" : ""} ${cut && !rejected ? "line-through" : ""}`}
                        style={
                          isMarked
                            ? { background: "#006FEE55", color: "#ECEDEE", boxShadow: "0 0 0 1px #006FEE" }
                            : cut
                            ? {
                                color: rejected ? "#71717A" : color,
                                background: isCurrent ? undefined : rejected ? "transparent" : `${color}22`,
                                boxShadow: isSelected ? `0 0 0 1px ${color}` : undefined,
                                borderBottom: open ? `1px dashed ${color}` : undefined,
                                textDecorationColor: rejected ? "transparent" : color,
                              }
                            : undefined
                        }
                        title={cut ? `${REASON_LABEL[cut.reason]} · ${cut.status}` : undefined}
                      >
                        {w.text}
                      </span>
                    );
                  }).reduce<React.ReactNode[]>((acc, el, i) => (i ? [...acc, " ", el] : [el]), [])}
                </p>
              </div>
            );
          })}
        </div>
      </div>
      {marked ? (
        <div role="region" aria-label="Markierung" className="flex flex-col gap-2 border-t border-primary bg-[#0b2447] px-4 py-2.5 text-xs">
          <div className="text-text">
            <span className="font-semibold">Wort {marked[0]}{marked[1] !== marked[0] && ` bis ${marked[1]}`}</span>
            <span className="text-text-muted"> · {rangeText(words, marked)}</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-1.5 text-text-muted">
              Grund
              <select
                aria-label="Grund des manuellen Cuts"
                value={markReason}
                onChange={(e) => setMarkReason(e.target.value as CutReason)}
                className="rounded-md border border-line-light bg-panel px-2 py-1 text-text"
              >
                {MANUAL_REASONS.map((r) => (
                  <option key={r} value={r}>
                    {REASON_LABEL[r]}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              onClick={save}
              disabled={markPending}
              className="rounded-md bg-primary px-3 py-1 font-semibold text-white disabled:opacity-50"
            >
              {markPending ? "Speichere …" : "Als Cut speichern (X)"}
            </button>
            <button type="button" onClick={() => setMarked(null)} className="rounded-md px-2 py-1 text-text-muted hover:text-text">
              Abbrechen (Esc)
            </button>
            {markError && <span className="text-[#F31260]">{markError}</span>}
          </div>
        </div>
      ) : (
        <div className="flex gap-3 border-t border-line px-4 py-2.5 text-xs text-text-muted">
          <span>Klick springt · Ziehen oder Shift-Klick markiert</span>
          <span className="ml-auto">Durchgestrichen = Cut, gestrichelt = offen</span>
        </div>
      )}
    </aside>
  );
}
