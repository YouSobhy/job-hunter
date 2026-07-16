"""JobHunter dashboard — run:  streamlit run dashboard.py

Shows run status, lets you fire the pipeline on demand (via the JobHunter
scheduled task, so manual and scheduled runs never collide), and browses
the jobs.jsonl history.
"""

import subprocess
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from jobhunter.notify import read_status
from jobhunter.results import load_jobs

st.set_page_config(page_title="JobHunter", page_icon="🎯", layout="wide")

TASK_NAME = "JobHunter"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def task_state() -> str:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-ScheduledTask -TaskName {TASK_NAME}).State"],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        )
        return out.stdout.strip() or "Unknown"
    except Exception:
        return "Unknown"


def fire_run() -> bool:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Start-ScheduledTask -TaskName {TASK_NAME}"],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        )
        return out.returncode == 0
    except Exception:
        return False


# -- Header / status ----------------------------------------------------------

st.title("🎯 JobHunter")

status = read_status()
state = task_state()
running = state == "Running"

col1, col2, col3, col4, col5 = st.columns([1.2, 1.2, 0.8, 0.8, 1])
col1.metric("Last run", (status.get("last_run") or "never")[:16].replace("T", " "))
col2.metric("Last success", (status.get("last_success") or "never")[:16].replace("T", " "))
col3.metric("New jobs", status.get("new_jobs", "—"))
col4.metric("Judged", status.get("judged", "—"))
col5.metric("Task state", state)

if status.get("error"):
    st.error(f"Last run error: {status['error']}")

if running:
    st.info("Run in progress… this page refreshes automatically.")
    time.sleep(5)
    st.rerun()
else:
    if st.button("▶ Run now", type="primary"):
        if fire_run():
            st.toast("Run started")
            time.sleep(2)
            st.rerun()
        else:
            st.error("Could not start the scheduled task.")

st.divider()

# -- Results table --------------------------------------------------------------

jobs = load_jobs()
if not jobs:
    st.info("No results yet — run the pipeline.")
    st.stop()

df = pd.DataFrame(jobs)
df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0).astype(int)
df = df.sort_values(["found", "score"], ascending=[False, False])

fcol1, fcol2, fcol3 = st.columns([1, 1, 2])
min_score = fcol1.slider("Min fit score", 0, 10, 0)
sources = fcol2.multiselect("Source", sorted(df["source"].unique()))
search = fcol3.text_input("Search title / company / summary")

view = df[df["score"] >= min_score]
if sources:
    view = view[view["source"].isin(sources)]
if search:
    s = search.lower()
    view = view[
        view["title"].str.lower().str.contains(s, na=False)
        | view["company"].str.lower().str.contains(s, na=False)
        | view["summary"].str.lower().str.contains(s, na=False)
    ]

st.caption(f"{len(view)} of {len(df)} jobs")
st.dataframe(
    view[["found", "title", "company", "location", "score", "tags", "summary", "url"]],
    hide_index=True,
    use_container_width=True,
    column_config={
        "found": st.column_config.TextColumn("Found", width="small"),
        "score": st.column_config.NumberColumn("Fit", width="small"),
        "url": st.column_config.LinkColumn("Link"),
        "summary": st.column_config.TextColumn("Summary", width="large"),
    },
)

st.caption(f"Data: jobs.jsonl · refreshed {datetime.now().strftime('%H:%M:%S')}")
