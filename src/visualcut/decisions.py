"""decisions.json lesen und schreiben. UI, CLI, MCP und Export nutzen nur dieses Modul."""

from __future__ import annotations

from .cache import ProjectCache
from .schema import Cut, CutStatus, Decision, Decisions

FILENAME = "decisions.json"


def load(cache: ProjectCache) -> Decisions:
    p = cache.path(FILENAME)
    if not p.exists():
        return Decisions(content_hash=cache.hash)
    return Decisions.model_validate_json(p.read_text(encoding="utf-8"))


def save(cache: ProjectCache, decisions: Decisions) -> None:
    cache.path(FILENAME).write_text(decisions.model_dump_json(indent=2), encoding="utf-8")


def set_status(cache: ProjectCache, cut_id: str, status: CutStatus, note: str = "") -> Decisions:
    d = load(cache)
    items = [i for i in d.items if i.cut_id != cut_id]
    if status != CutStatus.open or note:
        items.append(Decision(cut_id=cut_id, status=status, note=note))
    d.items = items
    save(cache, d)
    return d


def apply(cuts: list[Cut], decisions: Decisions) -> list[Cut]:
    """Status aus decisions.json auf die Cuts übertragen (Cuts selbst bleiben unverändert)."""
    m = decisions.as_map()
    out: list[Cut] = []
    for c in cuts:
        d = m.get(c.id)
        out.append(c.model_copy(update={"status": d.status}) if d else c)
    return out


def for_export(cuts: list[Cut], include_open: bool) -> tuple[list[Cut], list[Cut]]:
    """(zu schneidende Cuts, als Marker zu setzende Cuts). Verworfene fehlen in beiden."""
    cut_now = [c for c in cuts if c.status == CutStatus.accepted or (include_open and c.status == CutStatus.open)]
    markers = [] if include_open else [c for c in cuts if c.status == CutStatus.open]
    return cut_now, markers
