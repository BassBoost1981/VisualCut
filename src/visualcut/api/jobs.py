"""Analyse-Jobs im Hintergrund-Thread plus Fortschritts-Verteilung an WebSocket-Clients."""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..cache import ProjectCache
from ..ingest import StageError
from ..pipeline import run_analysis
from ..schema import ProgressEvent, Stage


@dataclass
class Job:
    id: str
    video: Path
    content_hash: str
    status: str = "running"  # running, done, failed
    error: str | None = None
    events: list[ProgressEvent] = field(default_factory=list)
    subscribers: set[asyncio.Queue] = field(default_factory=set)


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def start(self, video: Path, upto: Stage, force: bool, whisper_model: str, language: str) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], video=video, content_hash=ProjectCache.for_video(video).hash)
        self.jobs[job.id] = job
        try:
            self.loop = asyncio.get_running_loop()
        except RuntimeError:
            self.loop = None

        def progress(ev: ProgressEvent) -> None:
            self._publish(job, ev)

        def work() -> None:
            try:
                run_analysis(video, upto, force, progress, None, whisper_model, language)
                job.status = "done"
                self._publish(job, ProgressEvent(event="job_done", message=job.id))
            except (StageError, Exception) as e:  # noqa: BLE001
                job.status = "failed"
                job.error = str(e)
                self._publish(job, ProgressEvent(event="error", message=str(e)))

        threading.Thread(target=work, name=f"visualcut-{job.id}", daemon=True).start()
        return job

    def _publish(self, job: Job, ev: ProgressEvent) -> None:
        with self._lock:
            job.events.append(ev)
            subs = list(job.subscribers)
        if self.loop is None:
            return
        for q in subs:
            self.loop.call_soon_threadsafe(q.put_nowait, ev)

    def subscribe(self, job: Job) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            for ev in job.events:  # Nachzügler bekommen die Historie
                q.put_nowait(ev)
            job.subscribers.add(q)
        return q

    def unsubscribe(self, job: Job, q: asyncio.Queue) -> None:
        with self._lock:
            job.subscribers.discard(q)


manager = JobManager()
