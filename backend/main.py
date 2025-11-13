from fastapi import FastAPI, BackgroundTasks
from pydantic import BaseModel
from typing import List

app = FastAPI()

class CrawlRequest(BaseModel):
    sources: List[str]
    year_min: int | None = None
    year_max: int | None = None

class ManualPDFSubmit(BaseModel):
    pdf_urls: List[str]
    job_id: str | None = None

jobs = {}

@app.post("/crawl")
def crawl(req: CrawlRequest, background_tasks: BackgroundTasks):
    job_id = f"job-{len(jobs)+1}"
    jobs[job_id] = {"status": "queued", "processed": 0, "total": 0}
    background_tasks.add_task(run_job, job_id, req)
    return {"status": "started", "job_id": job_id}

@app.get("/job-status/{job_id}")
def job_status(job_id: str):
    return jobs.get(job_id, {"status": "unknown"})

@app.post("/manual-pdf-submit")
def manual_pdf_submit(req: ManualPDFSubmit):
    """Accept manually extracted PDF URLs for processing"""
    if req.job_id and req.job_id in jobs:
        # Add to existing job
        jobs[req.job_id]["total"] += len(req.pdf_urls)
        return {"status": "added to existing job", "job_id": req.job_id, "added": len(req.pdf_urls)}
    else:
        # Create new job
        job_id = f"job-{len(jobs)+1}"
        jobs[job_id] = {"status": "queued", "processed": 0, "total": len(req.pdf_urls)}
        return {"status": "new job created", "job_id": job_id, "total": len(req.pdf_urls)}

def run_job(job_id: str, req: CrawlRequest):
    # placeholder job runner
    import time
    jobs[job_id]["status"] = "running"
    jobs[job_id]["total"] = 3
    for i in range(3):
        time.sleep(2)
        jobs[job_id]["processed"] = i+1
    jobs[job_id]["status"] = "completed"
