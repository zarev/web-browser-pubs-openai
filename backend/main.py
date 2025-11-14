import logging
from typing import List, Union

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

from db import get_connection, get_sources, init_db, insert_paper, upsert_source
from harvest import harvest_source

app = FastAPI()
logger = logging.getLogger("publication_harvester")


class SourceInput(BaseModel):
    url: str
    label: str | None = None


class CrawlRequest(BaseModel):
    sources: List[Union[str, SourceInput]]
    year_min: int | None = None
    year_max: int | None = None


class ManualPDFSubmit(BaseModel):
    pdf_urls: List[str]
    job_id: str | None = None


jobs: dict[str, dict] = {}


@app.on_event("startup")
def on_startup():
    init_db()
    logger.info("Database initialized")


@app.post("/crawl")
def crawl(req: CrawlRequest, background_tasks: BackgroundTasks):
    job_id = f"job-{len(jobs) + 1}"
    jobs[job_id] = {"status": "queued", "processed": 0, "total": len(req.sources), "results": []}
    background_tasks.add_task(run_job, job_id, req)
    return {"status": "started", "job_id": job_id}


@app.get("/job-status/{job_id}")
def job_status(job_id: str):
    return jobs.get(job_id, {"status": "unknown"})


@app.get("/sources")
def list_sources(limit: int = 100):
    return get_sources(limit if limit > 0 else None)


@app.post("/sources")
def create_source(source: SourceInput):
    with get_connection() as conn:
        source_id = upsert_source(conn, source.url, source.label)
    return {"id": source_id, "url": source.url, "label": source.label}


@app.post("/manual-pdf-submit")
def manual_pdf_submit(req: ManualPDFSubmit):
    if req.job_id and req.job_id in jobs:
        jobs[req.job_id]["total"] += len(req.pdf_urls)
        manual_source_label = f"Manual submission for {req.job_id}"
        manual_job_id = req.job_id
    else:
        manual_job_id = f"job-{len(jobs) + 1}"
        jobs[manual_job_id] = {"status": "queued", "processed": 0, "total": len(req.pdf_urls), "results": []}
        manual_source_label = f"Manual submission for {manual_job_id}"

    manual_source_url = f"manual://{manual_job_id}"
    with get_connection() as conn:
        source_id = upsert_source(conn, manual_source_url, manual_source_label)
        inserted = 0
        for pdf_url in req.pdf_urls:
            if insert_paper(conn, source_id, pdf_url, None):
                inserted += 1

    return {
        "status": "accepted",
        "job_id": manual_job_id,
        "added": len(req.pdf_urls),
        "stored": inserted,
    }


def normalize_source_entry(entry: Union[str, SourceInput]) -> tuple[str, str | None]:
    if isinstance(entry, str):
        return entry, None
    return entry.url, entry.label


def run_job(job_id: str, req: CrawlRequest):
    jobs[job_id]["status"] = "running"
    if not req.sources:
        jobs[job_id]["status"] = "completed"
        return

    for index, entry in enumerate(req.sources, start=1):
        source_url, label = normalize_source_entry(entry)
        result = harvest_source(source_url, label)
        jobs[job_id]["processed"] = index
        jobs[job_id]["results"].append(result)

    jobs[job_id]["status"] = "completed"
