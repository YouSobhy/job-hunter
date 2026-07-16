"""JobHunter dashboard — run:  streamlit run dashboard.py  (or dashboard.bat)

Tabs: Jobs (card feed) · Custom search (saved searches + one-off) · Activity.
Runs always go through the JobHunter scheduled task so manual, custom, and
scheduled runs never collide.
"""

import html
import subprocess
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from jobhunter.notify import read_status
from jobhunter.results import load_jobs
from jobhunter.searches import (add_search, delete_search, load_saved,
                                parse_terms, update_search, write_request)

st.set_page_config(page_title="JobHunter", page_icon="🎯", layout="wide")

TASK_NAME = "JobHunter"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Palette: categorical slot-1 blue accent; status colors for score badges
ACCENT = "#2a78d6"
GOOD = "#0ca30c"      # fit >= 8
WARN = "#fab219"      # fit 6-7
INK2 = "#52514e"

st.markdown(f"""
<style>
.jh-badge {{
    display:inline-block; min-width:3.2em; text-align:center;
    padding:2px 10px; border-radius:999px; font-weight:700; font-size:0.95rem;
    color:#fff;
}}
.jh-badge.good {{ background:{GOOD}; }}
.jh-badge.warn {{ background:{WARN}; color:#0b0b0b; }}
.jh-badge.na   {{ background:#898781; }}
.jh-chip {{
    display:inline-block; padding:1px 9px; margin-right:6px;
    border-radius:999px; font-size:0.75rem; font-weight:600;
    background:#eef3fb; color:{ACCENT}; border:1px solid {ACCENT}33;
}}
.jh-meta {{ color:{INK2}; font-size:0.85rem; margin:2px 0 6px 0; }}
.jh-title a {{ text-decoration:none; color:#0b0b0b; }}
.jh-title a:hover {{ color:{ACCENT}; }}
.jh-title {{ font-size:1.08rem; font-weight:700; margin-bottom:0; }}
.jh-summary {{ font-size:0.92rem; margin-top:2px; }}
.jh-statuschip {{
    display:inline-block; padding:3px 12px; margin-right:8px;
    border-radius:999px; font-size:0.82rem; font-weight:600;
    background:#fcfcfb; border:1px solid #e1e0d9; color:{INK2};
}}
</style>
""", unsafe_allow_html=True)


# -- Task helpers ----------------------------------------------------------------

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


def fire_run(terms: list[str] | None = None, saved_index: int | None = None) -> bool:
    if terms:
        write_request(terms, source="dashboard")
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"Start-ScheduledTask -TaskName {TASK_NAME}"],
            capture_output=True, text=True, timeout=15, creationflags=_NO_WINDOW,
        )
        ok = out.returncode == 0
    except Exception:
        ok = False
    if ok and saved_index is not None:
        update_search(saved_index, last_run=datetime.now().isoformat(timespec="seconds"))
    return ok


# -- Header -----------------------------------------------------------------------

status = read_status()
state = task_state()
running = state == "Running"

hcol1, hcol2 = st.columns([3, 1])
with hcol1:
    st.markdown("## 🎯 JobHunter")
    last_run = (status.get("last_run") or "never")[:16].replace("T", " ")
    mode = status.get("mode", "scheduled")
    mode_txt = "custom: " + ", ".join(status.get("terms") or []) if mode == "custom" else "scheduled"
    chips = (
        f'<span class="jh-statuschip">last run&nbsp; <b>{html.escape(last_run)}</b></span>'
        f'<span class="jh-statuschip">{html.escape(mode_txt[:60])}</span>'
        f'<span class="jh-statuschip">found <b>{status.get("new_jobs", "—")}</b>'
        f' / judged <b>{status.get("judged", "—")}</b></span>'
        f'<span class="jh-statuschip">task: <b>{html.escape(state)}</b></span>'
    )
    st.markdown(chips, unsafe_allow_html=True)
with hcol2:
    st.write("")
    if running:
        st.button("⏳ Running…", disabled=True, use_container_width=True)
    else:
        if st.button("▶ Run now", type="primary", use_container_width=True):
            if fire_run():
                st.toast("Run started")
                time.sleep(2)
                st.rerun()
            else:
                st.error("Could not start the scheduled task.")

if status.get("error"):
    st.error(f"Last run error: {status['error']}")
if running:
    st.info("Run in progress — this page refreshes automatically.")
    time.sleep(5)
    st.rerun()

tab_jobs, tab_search, tab_activity = st.tabs(["🗂  Jobs", "🔍  Custom search", "📊  Activity"])


# -- Jobs tab ----------------------------------------------------------------------

with tab_jobs:
    jobs = load_jobs()
    if not jobs:
        st.info("No results yet — run the pipeline.")
    else:
        df = pd.DataFrame(jobs)
        df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0).astype(int)
        df = df.sort_values(["found", "score"], ascending=[False, False])

        with st.sidebar:
            st.markdown("### Filters")
            min_score = st.slider("Min fit score", 0, 10, 0)
            sources = st.multiselect("Source", sorted(df["source"].unique()))
            custom_only = st.checkbox("Custom-search results only")
            search = st.text_input("Search title / company / summary")
            max_cards = st.number_input("Cards shown", 10, 200, 40, step=10)

        view = df[df["score"] >= min_score]
        if sources:
            view = view[view["source"].isin(sources)]
        if custom_only:
            view = view[view["tags"].str.contains("CUSTOM", na=False)]
        if search:
            s = search.lower()
            view = view[
                view["title"].str.lower().str.contains(s, na=False)
                | view["company"].str.lower().str.contains(s, na=False)
                | view["summary"].str.lower().str.contains(s, na=False)
            ]

        st.caption(f"{len(view)} of {len(df)} jobs")
        for _, row in view.head(int(max_cards)).iterrows():
            score = int(row["score"])
            badge_cls = "good" if score >= 8 else ("warn" if score >= 6 else "na")
            summary, _, reason = (row.get("summary") or "").partition(" | ")
            chips_html = "".join(
                f'<span class="jh-chip">{html.escape(t.strip())}</span>'
                for t in (row.get("tags") or "").split(",") if t.strip()
            )
            meta = " · ".join(filter(None, [
                html.escape(str(row.get("company") or "")),
                html.escape(str(row.get("location") or "")),
                html.escape(str(row.get("source") or "")),
                f"found {html.escape(str(row.get('found') or ''))}",
            ]))
            with st.container(border=True):
                c1, c2 = st.columns([12, 1])
                with c1:
                    st.markdown(
                        f'<div class="jh-title"><a href="{html.escape(str(row["url"]))}" '
                        f'target="_blank">{html.escape(str(row["title"]))}</a></div>'
                        f'<div class="jh-meta">{meta}</div>'
                        + (f'<div>{chips_html}</div>' if chips_html else "")
                        + (f'<div class="jh-summary">{html.escape(summary)}</div>' if summary else ""),
                        unsafe_allow_html=True,
                    )
                    if reason:
                        with st.expander("Judge's reasoning"):
                            st.write(reason)
                with c2:
                    st.markdown(
                        f'<span class="jh-badge {badge_cls}">{score}</span>',
                        unsafe_allow_html=True,
                    )


# -- Custom search tab ----------------------------------------------------------------

with tab_search:
    st.markdown("Search for **specific job titles** — the pipeline runs once with "
                "your titles instead of the configured terms, and results land in "
                "the Jobs tab (tagged `CUSTOM`), the sheet, and Telegram.")

    with st.container(border=True):
        st.markdown("**One-off search**")
        oneoff = st.text_input(
            "Titles (comma-separated)",
            placeholder="hr systems analyst, payroll implementation consultant",
            label_visibility="collapsed",
        )
        if st.button("🔍 Search now", disabled=running or not oneoff.strip()):
            terms = parse_terms(oneoff)
            if terms and fire_run(terms):
                st.toast(f"Searching: {', '.join(terms)}")
                time.sleep(2)
                st.rerun()

    st.markdown("#### Saved searches")
    saved = load_saved()
    if not saved:
        st.caption("None yet — add one below.")
    for i, s in enumerate(saved):
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([5, 2, 1, 1])
            with c1:
                st.markdown(f"**{html.escape(s['name'])}**")
                st.caption(", ".join(s["terms"]))
            with c2:
                lr = (s.get("last_run") or "never")[:16].replace("T", " ")
                st.caption(f"last run: {lr}")
            with c3:
                if st.button("▶ Run", key=f"run{i}", disabled=running):
                    if fire_run(s["terms"], saved_index=i):
                        st.toast(f"Searching: {s['name']}")
                        time.sleep(2)
                        st.rerun()
            with c4:
                if st.button("🗑", key=f"del{i}"):
                    delete_search(i)
                    st.rerun()
            with st.expander("Edit"):
                new_name = st.text_input("Name", value=s["name"], key=f"nm{i}")
                new_terms = st.text_area("Titles (one per line or comma-separated)",
                                         value="\n".join(s["terms"]), key=f"tm{i}")
                if st.button("Save changes", key=f"sv{i}"):
                    update_search(i, name=new_name, terms=parse_terms(new_terms))
                    st.rerun()

    with st.expander("➕ Add a saved search"):
        a_name = st.text_input("Name", key="add_name",
                               placeholder="HRIS roles")
        a_terms = st.text_area("Titles (one per line or comma-separated)", key="add_terms",
                               placeholder="hris analyst\nhr systems analyst")
        if st.button("Add", disabled=not (a_name.strip() and a_terms.strip())):
            add_search(a_name, parse_terms(a_terms))
            st.rerun()


# -- Activity tab ------------------------------------------------------------------------

with tab_activity:
    jobs = load_jobs()
    if not jobs:
        st.info("No data yet.")
    else:
        df = pd.DataFrame(jobs)
        df["found_dt"] = pd.to_datetime(df["found"], errors="coerce")
        df = df.dropna(subset=["found_dt"])
        weekly = (
            df.set_index("found_dt")
            .resample("W-MON", label="left")
            .size()
            .rename("jobs")
            .reset_index()
        )
        weekly["week"] = weekly["found_dt"].dt.strftime("%b %d")

        st.markdown("#### Jobs found per week")
        st.bar_chart(weekly.set_index("week")["jobs"], color=ACCENT, height=260)

        c1, c2, c3 = st.columns(3)
        c1.metric("Total jobs stored", len(df))
        this_week = int(weekly["jobs"].iloc[-1]) if len(weekly) else 0
        c2.metric("This week", this_week)
        c3.metric("Sources", df["source"].nunique())

        st.markdown("#### Last run")
        s = read_status()
        st.write({
            "last_run": s.get("last_run"), "last_success": s.get("last_success"),
            "mode": s.get("mode"), "terms": s.get("terms"),
            "new_jobs": s.get("new_jobs"), "judged": s.get("judged"),
            "error": s.get("error"),
        })

st.caption(f"Data: jobs.jsonl · refreshed {datetime.now().strftime('%H:%M:%S')}")
