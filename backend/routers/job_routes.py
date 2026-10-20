"""Shared endpoints for a JobSlot: list, read (incremental log), download the log, cancel."""
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from ..services import audit, jobs


def add_job_routes(router: APIRouter, slot: Callable[[Request], jobs.JobSlot], name: str) -> None:
    @router.get("/jobs")
    def list_jobs(request: Request):
        s = slot(request)
        return {"jobs": s.store.jobs(), "busy": s.busy()}

    @router.get("/jobs/{job_id}")
    def get_job(job_id: int, request: Request, after: int | None = None):
        try:
            return slot(request).store.job(job_id, after)
        except jobs.JobError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/jobs/{job_id}/log")
    def download_log(job_id: int, request: Request):
        path = slot(request).store.log_path(job_id)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="The log file is gone.")
        return FileResponse(path, media_type="text/plain", filename=f"{name}-{job_id}.log")

    @router.post("/jobs/{job_id}/cancel")
    def cancel(job_id: int, request: Request):
        if not slot(request).cancel(job_id):
            raise HTTPException(status_code=409, detail="That job is not running.")
        audit.record(request, f"{name}.cancel", f"job #{job_id}", "WARN")
        return {"ok": True}
