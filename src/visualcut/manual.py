"""manual.json lesen und schreiben: Cuts, die der Mensch im Transkript markiert hat.

Manuelle Cuts haben nur Wort-IDs und `source=manual`, sind sofort angenommen und laufen durch dieselbe Fusion
wie Regel- und LLM-Cuts. UI, CLI und API nutzen nur dieses Modul (über `pipeline.mark` / `pipeline.unmark`).
"""

from __future__ import annotations

import hashlib

from .cache import ProjectCache
from .schema import Cut, CutReason, CutSource, CutStatus, ManualCuts, Word

FILENAME = "manual.json"


def load(cache: ProjectCache) -> ManualCuts:
    p = cache.path(FILENAME)
    if not p.exists():
        return ManualCuts(content_hash=cache.hash)
    return ManualCuts.model_validate_json(p.read_text(encoding="utf-8"))


def save(cache: ProjectCache, manual: ManualCuts) -> None:
    cache.path(FILENAME).write_text(manual.model_dump_json(indent=2), encoding="utf-8")


def add(cache: ProjectCache, words: list[Word], start_word: int, end_word: int,
        reason: CutReason = CutReason.redundant, note: str = "") -> Cut:
    """Wortspanne als manuellen Cut speichern. Ungültige IDs sind ein Eingabefehler, nichts wird korrigiert."""
    ids = {w.id for w in words}
    if start_word not in ids or end_word not in ids:
        raise ValueError(f"Wort-ID außerhalb des Transkripts: {start_word}-{end_word}")
    if end_word < start_word:
        raise ValueError(f"end_word {end_word} < start_word {start_word}")
    if reason == CutReason.long_pause:
        raise ValueError("Manuelle Cuts schneiden Wörter, long_pause ist dafür nicht vorgesehen")
    cut = Cut(id=f"manual-{start_word}-{end_word}", start_word=start_word, end_word=end_word, reason=reason,
              confidence=1.0, source=CutSource.manual, note=note, status=CutStatus.accepted)
    m = load(cache)
    m.cuts = sorted([c for c in m.cuts if c.id != cut.id] + [cut], key=lambda c: (c.start_word, c.end_word))
    save(cache, m)
    return cut


def owner(manual: ManualCuts, cut_id: str) -> Cut | None:
    """Manueller Cut zu einer Cut-ID nach der Fusion (an Szenenwechseln geteilt: `<id>.0`, `<id>.1`)."""
    return next((c for c in manual.cuts if cut_id == c.id or cut_id.startswith(c.id + ".")), None)


def remove(cache: ProjectCache, cut_id: str) -> Cut:
    m = load(cache)
    hit = owner(m, cut_id)
    if hit is None:
        raise ValueError(f"Kein manueller Cut {cut_id}")
    m.cuts = [c for c in m.cuts if c.id != hit.id]
    save(cache, m)
    return hit


def fingerprint(manual: ManualCuts) -> str | None:
    """Kennung der manuellen Cuts, damit die Fusion nach jeder Markierung neu rechnet."""
    if not manual.cuts:
        return None
    h = hashlib.sha1()
    for c in manual.cuts:
        h.update(f"{c.id}:{c.reason.value}:{c.note}".encode())
    return h.hexdigest()[:16]
