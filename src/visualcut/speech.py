"""Stufe 2: faster-whisper large-v3 auf CUDA mit VAD, whisperX-Wort-Alignment, regelbasierte Cuts."""

from __future__ import annotations

import gc
import re
from pathlib import Path

from .cache import ProgressFn, ProjectCache, emit
from .ingest import StageError
from .schema import Cut, CutReason, CutSource, MediaInfo, SpeechResult, Stage, Word

PRIMARY_MODEL = "large-v3"
FALLBACK_MODEL = "medium"

# Regelparameter
FILLERS = {"ähm": 0.9, "äh": 0.9, "ähm,": 0.9, "hm": 0.7, "mhm": 0.7, "halt": 0.6, "quasi": 0.65, "sozusagen": 0.65}
SENTENCE_START_FILLERS = {"also": 0.7}
RETAKE_MIN_WORDS = 5
RETAKE_WINDOW_S = 15.0
RETAKE_FUZZ = 85
LONG_PAUSE_S = 1.2


def _log(msg: str) -> None:
    sys.stderr.write(f'{{"event":"log","message":{msg!r}}}\n'.replace("'", '"'))


# ---------------------------------------------------------------- Transkription


def _pick_device() -> str:
    try:
        import torch  # noqa: F401  (lädt auf Windows die CUDA-DLLs für ctranslate2)

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _load_wav(audio: Path):
    """16-kHz-Mono-WAV als float32-Array. Umgeht das PyAV-Decoding von faster-whisper
    (PyAV >= 16 kennt metadata_errors nicht mehr)."""
    import wave

    import numpy as np

    with wave.open(str(audio), "rb") as w:
        assert w.getnchannels() == 1 and w.getframerate() == 16000 and w.getsampwidth() == 2, "erwarte 16 kHz mono s16"
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return data.astype(np.float32) / 32768.0


def _load_model(size: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(size, device=device, compute_type=compute_type)


def _is_oom(exc: BaseException) -> bool:
    s = str(exc).lower()
    return "out of memory" in s or "cuda_error_out_of_memory" in s or "cublas" in s


def _free_gpu(*objs) -> None:
    for o in objs:
        del o
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _transcribe_segments(audio: Path, language: str, model_size: str, progress: ProgressFn | None, duration: float):
    """Gibt (segments, model_name, device) zurück. Fällt bei VRAM-Mangel auf medium int8 zurück."""
    device = _pick_device()
    attempts = [(model_size, "float16" if device == "cuda" else "int8")]
    if device == "cuda" and model_size != FALLBACK_MODEL:
        attempts.append((FALLBACK_MODEL, "int8_float16"))
    last: BaseException | None = None
    for size, ctype in attempts:
        model = None
        try:
            emit(progress, "progress", Stage.speech, f"Lade {size} ({device}, {ctype})", 5)
            model = _load_model(size, device, ctype)
            seg_iter, _info = model.transcribe(
                _load_wav(audio), language=language, vad_filter=True, word_timestamps=True, beam_size=5,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            segments = []
            for seg in seg_iter:
                segments.append({
                    "start": float(seg.start), "end": float(seg.end), "text": seg.text,
                    "words": [
                        {"word": w.word, "start": float(w.start), "end": float(w.end), "score": float(w.probability)}
                        for w in (seg.words or [])
                    ],
                })
                if duration > 0:
                    emit(progress, "progress", Stage.speech, "Transkribiere", 5 + 55 * min(seg.end / duration, 1.0))
            _free_gpu(model)
            return segments, size, device
        except Exception as e:  # noqa: BLE001
            last = e
            _free_gpu(model)
            if _is_oom(e) and size != attempts[-1][0]:
                emit(progress, "log", Stage.speech, f"VRAM reicht nicht für {size}, Fallback auf {FALLBACK_MODEL} int8")
                continue
            raise StageError(f"Transkription fehlgeschlagen: {e}") from e
    raise StageError(f"Transkription fehlgeschlagen: {last}")


def _align(segments: list[dict], audio: Path, language: str, device: str, progress: ProgressFn | None) -> list[dict] | None:
    """whisperX-Alignment. Gibt Wortliste [{word,start,end,score}] oder None bei Fehler."""
    try:
        import whisperx
    except Exception as e:  # noqa: BLE001
        emit(progress, "log", Stage.speech, f"whisperX nicht verfügbar: {e}")
        return None
    model_a = None
    try:
        emit(progress, "progress", Stage.speech, "Wort-Alignment (whisperX)", 65)
        model_a, meta = whisperx.load_align_model(language_code=language, device=device)
        wav = whisperx.load_audio(str(audio))
        result = whisperx.align(
            [{"start": s["start"], "end": s["end"], "text": s["text"]} for s in segments],
            model_a, meta, wav, device, return_char_alignments=False,
        )
        words = [w for w in result.get("word_segments", []) if w.get("word", "").strip()]
        return words
    except Exception as e:  # noqa: BLE001
        emit(progress, "log", Stage.speech, f"whisperX-Alignment fehlgeschlagen, nutze Whisper-Wortzeiten: {e}")
        return None
    finally:
        _free_gpu(model_a)


def _to_words(raw: list[dict], fallback_conf: float = 0.5) -> list[Word]:
    """Fehlende Zeitstempel (whisperX lässt Zahlen aus) aus den Nachbarn interpolieren."""
    words: list[Word] = []
    n = len(raw)
    for i, w in enumerate(raw):
        start = w.get("start")
        end = w.get("end")
        if start is None or end is None:
            prev_end = next((raw[j]["end"] for j in range(i - 1, -1, -1) if raw[j].get("end") is not None), 0.0)
            next_start = next((raw[j]["start"] for j in range(i + 1, n) if raw[j].get("start") is not None), prev_end)
            start, end = prev_end, max(prev_end, next_start)
        words.append(Word(
            id=len(words), text=w["word"].strip(), start=float(start), end=max(float(start), float(end)),
            confidence=min(1.0, max(0.0, float(w.get("score", fallback_conf) or fallback_conf))),
        ))
    return words


def transcribe(
    media: MediaInfo, cache: ProjectCache, progress: ProgressFn | None = None, force: bool = False,
    model_size: str = PRIMARY_MODEL, language: str = "de",
) -> SpeechResult:
    stage = Stage.speech
    if cache.has(stage) and not force:
        emit(progress, "stage_skipped", stage, "Cache vorhanden")
        return cache.load(stage, SpeechResult)
    emit(progress, "stage_start", stage)
    if not media.audio_path or not Path(media.audio_path).exists():
        result = SpeechResult(words=[], language=language, model="", device="", aligned=False, text="")
        cache.save(stage, result)
        emit(progress, "stage_done", stage, "Keine Audiospur, leeres Transkript")
        return result
    audio = Path(media.audio_path)
    segments, used_model, device = _transcribe_segments(audio, language, model_size, progress, media.duration)
    aligned_words = _align(segments, audio, language, device, progress) if segments else []
    aligned = aligned_words is not None
    raw = aligned_words if aligned else [w for s in segments for w in s["words"]]
    words = _to_words(raw)
    result = SpeechResult(
        words=words, language=language, model=used_model, device=device, aligned=aligned,
        text=" ".join(w.text for w in words),
    )
    cache.save(stage, result)
    emit(progress, "stage_done", stage, f"{len(words)} Wörter, Modell {used_model} auf {device}")
    return result


# ---------------------------------------------------------------- Regelbasierte Cuts

_PUNCT = re.compile(r"[^\wäöüß]+", re.IGNORECASE)


def _norm(text: str) -> str:
    return _PUNCT.sub("", text.lower())


def _ends_sentence(text: str) -> bool:
    return text.rstrip().endswith((".", "!", "?"))


def filler_cuts(words: list[Word]) -> list[Cut]:
    cuts: list[Cut] = []
    for i, w in enumerate(words):
        key = _norm(w.text)
        conf = FILLERS.get(key)
        if conf is None and key in SENTENCE_START_FILLERS:
            at_start = i == 0 or _ends_sentence(words[i - 1].text) or (w.start - words[i - 1].end) > 0.5
            if at_start:
                conf = SENTENCE_START_FILLERS[key]
        if conf is None:
            continue
        cuts.append(Cut(
            id=f"filler-{w.id}", start_word=w.id, end_word=w.id, reason=CutReason.filler,
            confidence=conf, source=CutSource.rule, note=f"Füllwort „{w.text}“",
        ))
    return cuts


def retake_cuts(words: list[Word]) -> list[Cut]:
    """Gleiche Wortfolge (fuzzy, >= 5 Wörter) zweimal innerhalb von 15 s: erste Instanz wird Kandidat."""
    from rapidfuzz import fuzz

    norm = [_norm(w.text) for w in words]
    n = len(words)
    k = RETAKE_MIN_WORDS

    def window(a: int, b: int, length: int) -> float:
        return fuzz.ratio(" ".join(norm[a : a + length]), " ".join(norm[b : b + length]))

    cuts: list[Cut] = []
    i = 0
    while i + 2 * k <= n:
        # Anker: das k-Wort-Fenster ab i muss ab einem späteren j (innerhalb 15 s) fuzzy wiederkehren.
        # Verglichen wird nur das Startfenster, damit lange Fenster Unterschiede nicht verwässern.
        best: tuple[int, float] | None = None
        for j in range(i + k, n - k + 1):
            if words[j].start - words[i].start > RETAKE_WINDOW_S:
                break
            score = window(i, j, k)
            if score >= RETAKE_FUZZ and (best is None or score > best[1]):
                best = (j, score)
        if best is None:
            i += 1
            continue
        j, score = best
        length = k
        while i + length < j and j + length < n and window(i + length, j + length, 1) >= RETAKE_FUZZ:
            length += 1  # Übereinstimmung Wort für Wort verlängern
        cuts.append(Cut(
            id=f"retake-{words[i].id}", start_word=words[i].id, end_word=words[j - 1].id, reason=CutReason.retake,
            confidence=round(0.6 + 0.3 * (score - RETAKE_FUZZ) / (100 - RETAKE_FUZZ), 2), source=CutSource.rule,
            note=f"Wiederholung ab Wort {words[j].id}: „{' '.join(w.text for w in words[j:j + length])}“",
        ))
        i = j
    return cuts


def long_pause_cuts(words: list[Word]) -> list[Cut]:
    """Stille > 1,2 s zwischen zwei Wörtern. start_word/end_word sind die beiden Nachbarwörter,
    die Fusion nimmt die Lücke dazwischen (die Wörter selbst bleiben erhalten)."""
    cuts: list[Cut] = []
    for a, b in zip(words, words[1:]):
        gap = b.start - a.end
        if gap > LONG_PAUSE_S:
            cuts.append(Cut(
                id=f"pause-{a.id}", start_word=a.id, end_word=b.id, reason=CutReason.long_pause,
                confidence=min(0.95, 0.7 + (gap - LONG_PAUSE_S) * 0.1), source=CutSource.rule,
                note=f"Pause {gap:.2f} s",
            ))
    return cuts


def rule_cuts(words: list[Word]) -> list[Cut]:
    return filler_cuts(words) + retake_cuts(words) + long_pause_cuts(words)
