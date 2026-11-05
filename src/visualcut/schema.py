"""Pydantic-Datenmodelle. Einzige Quelle für `visualcut schema` und die API."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = 1


class Stage(StrEnum):
    ingest = "ingest"
    technical = "technical"
    events = "events"
    speech = "speech"
    semantic = "semantic"
    fusion = "fusion"


STAGE_ORDER: list[Stage] = [Stage.ingest, Stage.technical, Stage.events, Stage.speech, Stage.semantic, Stage.fusion]


class CutReason(StrEnum):
    filler = "filler"
    retake = "retake"
    tangent = "tangent"
    long_pause = "long_pause"
    false_start = "false_start"
    redundant = "redundant"
    technical = "technical"


class CutSource(StrEnum):
    rule = "rule"
    llm = "llm"
    manual = "manual"


class CutStatus(StrEnum):
    """offen / angenommen / verworfen"""

    open = "open"
    accepted = "accepted"
    rejected = "rejected"


class MediaInfo(BaseModel):
    """Stufe 0: ffprobe-Metadaten des Originals."""

    path: str
    content_hash: str
    size_bytes: int
    duration: float = Field(ge=0, description="Sekunden")
    fps: float = Field(gt=0, description="Nominale Framerate, bei VFR die durchschnittliche")
    variable_framerate: bool = False
    width: int
    height: int
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_channels: int = 0
    audio_sample_rate: int = 0
    has_audio: bool = False
    proxy_path: str | None = None
    audio_path: str | None = None
    frame_count: int = Field(default=0, ge=0)


class Word(BaseModel):
    """Ein Wort aus Stufe 2. `id` ist die stabile Referenz für Cuts und das LLM."""

    id: int = Field(ge=0)
    text: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    speaker: str | None = None
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def _check_order(self) -> Word:
        if self.end < self.start:
            raise ValueError(f"word {self.id}: end < start")
        return self


class SilenceInterval(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(ge=0)

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2


class SceneChange(BaseModel):
    frame: int = Field(ge=0, description="Erster Frame der neuen Szene")
    time: float = Field(ge=0, description="Sekunden")
    detector: str = Field(description="content, adaptive oder content+adaptive")
    score: float | None = None


class TechnicalResult(BaseModel):
    """Stufe 1: nur Messung, keine Interpretation."""

    silences: list[SilenceInterval] = []
    scenes: list[SceneChange] = []
    silence_threshold_db: float = -35.0
    silence_min_duration: float = 0.15


class SpeechResult(BaseModel):
    """Stufe 2: Transkript als Wortliste plus Modellinfo."""

    words: list[Word] = []
    language: str = "de"
    model: str = ""
    device: str = ""
    aligned: bool = False
    text: str = ""


class Cut(BaseModel):
    """Ein Schnittvorschlag. Vor der Fusion nur Wort-IDs, danach auch Sekunden und Frames."""

    id: str
    start_word: int = Field(ge=0)
    end_word: int = Field(ge=0)
    reason: CutReason
    confidence: float = Field(ge=0, le=1)
    source: CutSource = CutSource.rule
    note: str = ""
    status: CutStatus = CutStatus.open
    start: float | None = Field(default=None, description="Sekunden, nach Fusion")
    end: float | None = None
    start_frame: int | None = None
    end_frame: int | None = None
    maybe: bool = Field(default=False, description="confidence < 0.6")

    @model_validator(mode="after")
    def _check(self) -> Cut:
        if self.end_word < self.start_word:
            raise ValueError(f"cut {self.id}: end_word < start_word")
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(f"cut {self.id}: end < start")
        return self


class Chapter(BaseModel):
    """Stufe 3: inhaltlicher Abschnitt, nur Wort-IDs."""

    title: str
    start_word: int = Field(ge=0)
    end_word: int = Field(ge=0)


class Highlight(BaseModel):
    start_word: int = Field(ge=0)
    end_word: int = Field(ge=0)
    score: float = Field(ge=0, le=1)
    hook: str = ""
    start: float | None = Field(default=None, description="Sekunden, nach Fusion (an Event-Grenzen ausgerichtet)")
    end: float | None = None
    event_ids: list[str] = Field(default=[], description="Events, an denen der Clip ausgerichtet wurde")


class Flag(BaseModel):
    word: int = Field(ge=0)
    type: str = Field(description="z. B. unclear_audio, name_unclear, fact_check")


class LLMCut(BaseModel):
    """Ein Cut, wie das Modell ihn liefert (Structured Output). Ohne Constraints: validiert wird im Code."""

    start_word: int
    end_word: int
    reason: CutReason
    confidence: float
    note: str


class LLMChapter(BaseModel):
    title: str
    start_word: int
    end_word: int


class LLMHighlight(BaseModel):
    start_word: int
    end_word: int
    score: float
    hook: str


class LLMFlag(BaseModel):
    word: int
    type: str


class LLMResponse(BaseModel):
    """JSON-Schema für die Claude-Antwort pro Block (PLAN.md Abschnitt 3, Stufe 3)."""

    chapters: list[LLMChapter]
    cuts: list[LLMCut]
    highlights: list[LLMHighlight]
    flags: list[LLMFlag]


class SemanticSubmission(BaseModel):
    """Stufe 3 von außen: der steuernde Agent (Claude Code, Codex, ...) liefert dieselben Felder wie die
    Claude API, nur Wort-IDs. Alle Listen optional, `source` benennt den Absender."""

    source: str = Field(default="agent", description="z. B. agent:claude-code, agent:codex")
    chapters: list[LLMChapter] = []
    cuts: list[LLMCut] = []
    highlights: list[LLMHighlight] = []
    flags: list[LLMFlag] = []

    def as_response(self) -> LLMResponse:
        return LLMResponse(chapters=self.chapters, cuts=self.cuts, highlights=self.highlights, flags=self.flags)


class SemanticResult(BaseModel):
    """Stufe 3: validierte LLM-Ausgabe. Cuts haben source=llm und nur Wort-IDs, keine Sekunden."""

    chapters: list[Chapter] = []
    cuts: list[Cut] = []
    highlights: list[Highlight] = []
    flags: list[Flag] = []
    model: str = ""
    prompt_version: str = ""
    blocks: int = 0
    rejected: int = Field(default=0, description="Verworfene Einträge (ungültige IDs, Grenzen, Werte)")


class EventStatus(StrEnum):
    confirmed = "confirmed"
    candidate = "candidate"


class EventEffect(StrEnum):
    """Wirkung eines Event-Typs: Highlight-Kandidat, nur Marker, oder Schnitt-Kandidat."""

    highlight = "highlight"
    marker = "marker"
    cut = "cut"


class EventDefinition(BaseModel):
    """Ein Eintrag in events.yaml."""

    type: str = Field(pattern=r"^[a-z][a-z0-9_]*$", description="Stabiler Schlüssel, z. B. dancing")
    label: str = Field(description="Anzeigename")
    prompt: str = Field(default="", description="Text für X-CLIP (Zero-Shot), leer = kein Bild-Prompt")
    audio_prompt: str = Field(default="", description="Text für CLAP (Zero-Shot), leer = kein Audio-Prompt")
    kinetics: list[str] = Field(default=[], description="Teilstrings von Kinetics-400-Klassen, die VideoMAE als Bestätigung zählt")
    effect: EventEffect = EventEffect.marker
    background: bool = Field(default=False, description="Nur Vergleichsklasse für X-CLIP/CLAP, erzeugt kein Event")
    motion: bool = Field(default=False, description="Grenzen aus der Pose-Bewegungsenergie verfeinern")


class EventCatalog(BaseModel):
    """events.yaml: Liste der erkennbaren Ereignisse, pro Projekt überschreibbar."""

    version: int = 1
    vision_budget: int = Field(default=40, ge=0, description="Maximale Vision-LLM-Aufrufe pro Video (Ebene C)")
    events: list[EventDefinition] = []

    @model_validator(mode="after")
    def _unique(self) -> EventCatalog:
        seen: set[str] = set()
        for d in self.events:
            if d.type in seen:
                raise ValueError(f"Event-Typ {d.type} doppelt")
            seen.add(d.type)
        return self


class Event(BaseModel):
    """Ein Ereignis aus Stufe 1b. Sekunden kommen aus der Erkennung, nie von einem LLM."""

    id: str
    type: str
    label: str = ""
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    sources: list[str] = Field(default=[], description="pose, clap, xclip, videomae, vision, agent:<name>")
    status: EventStatus = EventStatus.candidate
    effect: EventEffect = EventEffect.marker
    description: str | None = None

    @model_validator(mode="after")
    def _check(self) -> Event:
        if self.end < self.start:
            raise ValueError(f"event {self.id}: end < start")
        return self


class EventWindow(BaseModel):
    """Ein unklares Fenster für Ebene C (Vision-LLM oder der steuernde Agent)."""

    id: str
    start: float = Field(ge=0)
    end: float = Field(ge=0)
    candidates: list[str] = Field(default=[], description="Event-Typen, um die es geht")
    reason: str = ""
    frames: list[str] = Field(default=[], description="JPEG-Pfade im Cache, 4 bis 8 Frames")
    judged_by: str | None = None


class EventJudgment(BaseModel):
    """Urteil zu einem Fenster: ein Typ aus events.yaml oder `none`. Keine Zeitangaben, die kommen aus dem Fenster."""

    window_id: str
    type: str
    confidence: float = Field(ge=0, le=1)
    description: str = ""


class LLMEventJudgment(BaseModel):
    """Structured Output der Vision-LLM-Antwort pro Fenster. Ohne Constraints: validiert wird im Code."""

    type: str
    confidence: float
    description: str


class EventJudgments(BaseModel):
    """Einreichung von Ebene C durch den steuernden Agenten (`visualcut events --judge`)."""

    source: str = "agent"
    judgments: list[EventJudgment] = []


class EventsResult(BaseModel):
    """Stufe 1b, entspricht events.json."""

    events: list[Event] = []
    detections: list[Event] = Field(default=[], description="Rohdetektionen pro Quelle, vor der Fusion")
    windows: list[EventWindow] = []
    judgments: list[EventJudgment] = []
    motion: list[float] = Field(default=[], description="Bewegungsenergie der Hauptperson pro Pose-Sample")
    motion_lower: list[float] = Field(default=[], description="Unterkörperenergie pro Pose-Sample, 0 wenn nicht sichtbar")
    motion_fps: float = 5.0
    layers: dict[str, str] = Field(default={}, description="Ebene/Modell -> ok oder Grund fürs Überspringen")
    vision_calls: int = 0
    vision_budget: int = 40
    detection_hash: str = Field(default="", description="Hash der erkennungsrelevanten Felder aus events.yaml")


class FusionResult(BaseModel):
    cuts: list[Cut] = []
    highlights: list[Highlight] = []
    fps: float = 25.0
    llm_model: str | None = Field(default=None, description="Modell der LLM-Cuts, die eingeflossen sind, sonst null")
    semantic_fingerprint: str | None = Field(default=None, description="Hash der eingeflossenen Stufe-3-Cuts, für den Cache")
    events_fingerprint: str | None = Field(default=None, description="Hash der eingeflossenen Events, für den Cache")


class Analysis(BaseModel):
    """Gesamtergebnis, entspricht analysis.json."""

    schema_version: int = SCHEMA_VERSION
    media: MediaInfo
    technical: TechnicalResult | None = None
    events: list[Event] = []
    speech: SpeechResult | None = None
    semantic: SemanticResult | None = None
    cuts: list[Cut] = []
    highlights: list[Highlight] = Field(default=[], description="Highlights mit Sekunden, nach Fusion")
    stages_done: list[Stage] = []


class Decision(BaseModel):
    cut_id: str
    status: CutStatus
    note: str = ""


class Decisions(BaseModel):
    """decisions.json: Entscheidungen der UI oder eines Agenten, von Export/CLI/MCP gelesen."""

    schema_version: int = SCHEMA_VERSION
    content_hash: str
    items: list[Decision] = []

    def as_map(self) -> dict[str, Decision]:
        return {d.cut_id: d for d in self.items}


class ProgressEvent(BaseModel):
    """Eine JSON-Line auf stderr bzw. eine WebSocket-Nachricht."""

    event: str = Field(description="stage_start, progress, stage_done, stage_skipped, error, log")
    stage: Stage | None = None
    percent: float | None = Field(default=None, ge=0, le=100)
    message: str = ""
    data: dict[str, Any] = {}


def json_schema() -> dict[str, Any]:
    """JSON-Schema aller Ausgabeobjekte unter einem gemeinsamen $defs-Dach."""
    from pydantic import TypeAdapter

    adapter = TypeAdapter(Analysis | Decisions | ProgressEvent | Cut | EventCatalog | EventsResult | EventJudgments)
    return adapter.json_schema()
