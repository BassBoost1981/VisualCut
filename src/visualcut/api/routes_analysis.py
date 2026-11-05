"""Analyse starten und Job-Status abfragen."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..schema import ProgressEvent, Stage
from ..semantic import DEFAULT_MODEL
from .jobs import manager

router = APIRouter(tags=["analysis"])


class AnalyzeRequest(BaseModel):
    path: str
    stage: Stage = Stage.fusion
    force: bool = False
    whisper_model: str = "large-v3"
    language: str = "de"
    llm: bool = True
    llm_model: str = DEFAULT_MODEL
    events: bool = True
    vision: bool = True


class JobInfo(BaseModel):
    job_id: str
    content_hash: str
    status: str
    error: str | None = None
    events: list[ProgressEvent] = []


def _info(job, with_events: bool = False) -> JobInfo:
    return JobInfo(job_id=job.id, content_hash=job.content_hash, status=job.status, error=job.error,
                   events=job.events if with_events else [])


@router.post("/analyze", response_model=JobInfo, status_code=202)
def start_analysis(body: AnalyzeRequest) -> JobInfo:
    video = Path(body.path)
    if not video.is_file():
        raise HTTPException(422, f"Datei nicht gefunden: {video}")
    job = manager.start(video, body.stage, body.force, body.whisper_model, body.language, body.llm, body.llm_model,
                        body.events, body.vision)
    return _info(job)


@router.get("/jobs/{job_id}", response_model=JobInfo)
def get_job(job_id: str) -> JobInfo:
    job = manager.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Job nicht gefunden")
    return _info(job, with_events=True)
