from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import json
import subprocess
import os

from jobhunter.feedback import save_feedback, load_feedback
from jobhunter.notify import read_status
from jobhunter.results import load_jobs
from jobhunter.searches import write_request
from jobhunter.config import BASE_DIR
from gcs_sync import pull_files, push_files, is_cloud
from fastapi import Request

app = FastAPI(title="JobHunter API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# @app.middleware("http")
# async def gcs_sync_middleware(request: Request, call_next):
#    return await call_next(request)

TASK_NAME = "JobHunter"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

def fire_run(terms=None):
    if terms:
        write_request(terms, source="dashboard")
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", f"Start-ScheduledTask -TaskName {TASK_NAME}"],
        capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
    )

@app.get("/api/status")
def get_status():
    status = read_status()
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", f"(Get-ScheduledTask -TaskName {TASK_NAME}).State"],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        )
        state = out.stdout.strip() or "Unknown"
    except Exception:
        state = "Unknown"
    status["task_state"] = state
    return status

@app.get("/api/jobs")
def get_jobs():
    jobs = load_jobs()
    fb = load_feedback()
    for j in jobs:
        j["fb_cat"] = fb.get(j["url"], {}).get("category")
        j["fb_label"] = fb.get(j["url"], {}).get("label")
        
        src = str(j.get("source", "")).lower()
        tags = str(j.get("tags", "")).lower()
        title = str(j.get("title", "")).lower()
        summary = str(j.get("summary", "")).lower()
        
        freelance = any(k in src for k in ("upwork", "hacker news", "remoteok", "freelance", "contract")) or \
                    any(k in tags for k in ("freelance", "contract", "side_role")) or \
                    any(k in title or k in summary for k in ("freelance", "contractor", "contract role", "gig", "part-time", "part time", "fractional"))
        j["is_freelance"] = freelance
        j["score"] = int(j.get("score") or 0)
        
        found_str = str(j.get("found", ""))[:10]
        if found_str:
            try:
                from datetime import datetime, date
                found_date = datetime.strptime(found_str, "%Y-%m-%d").date()
                age_days = (date.today() - found_date).days
                j["age_days"] = age_days
                if age_days > 14 and not j.get("fb_cat"):
                    j["fb_cat"] = "expired"
            except Exception:
                pass

    
    # Sort: highest score first, then newest
    jobs.sort(key=lambda x: (x.get("score", 0), x.get("found", "")), reverse=True)
    return jobs

class FeedbackReq(BaseModel):
    url: str
    category: str

@app.post("/api/feedback")
def post_feedback(req: FeedbackReq):
    save_feedback(req.url, req.category)
    return {"status": "ok"}

class RunReq(BaseModel):
    terms: list[str] = None

@app.post("/api/run_search")
def run_search(req: RunReq, bg: BackgroundTasks):
    bg.add_task(fire_run, req.terms)
    return {"status": "started"}

@app.get("/")
def serve_ui():
    return FileResponse("ui/index.html")
