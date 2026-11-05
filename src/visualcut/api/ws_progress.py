"""WebSocket, der die JSON-Lines-Fortschrittsmeldungen eines Jobs weiterreicht."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .jobs import manager

router = APIRouter(tags=["progress"])


@router.websocket("/ws/progress/{job_id}")
async def ws_progress(ws: WebSocket, job_id: str) -> None:
    job = manager.jobs.get(job_id)
    if job is None:
        await ws.close(code=4004, reason="Job nicht gefunden")
        return
    await ws.accept()
    manager.loop = asyncio.get_running_loop()
    q = manager.subscribe(job)
    try:
        while True:
            if q.empty() and job.status != "running":
                await ws.send_json({"event": "closed", "message": job.status, "data": {}})
                break
            try:
                ev = await asyncio.wait_for(q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            await ws.send_text(ev.model_dump_json(exclude_none=True))
    except WebSocketDisconnect:
        pass
    finally:
        manager.unsubscribe(job, q)
