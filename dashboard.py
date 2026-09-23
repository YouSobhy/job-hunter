"""JobHunter dashboard — run:  streamlit run dashboard.py  (or dashboard.bat)

Tabs: Jobs (card feed) · Custom search (saved searches + one-off) · Activity.
"""

import html
import subprocess
import time
from datetime import datetime

import pandas as pd
import streamlit as st

from jobhunter.feedback import CATEGORIES, load_feedback, save_feedback
from jobhunter.notify import read_status
from jobhunter.results import load_jobs
from jobhunter.searches import (add_search, delete_search, load_saved,
                                parse_terms, update_search, write_request)

st.set_page_config(page_title="JobHunter Dashboard", page_icon="🎯", layout="wide")

TASK_NAME = "JobHunter"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Styling Palette
ACCENT = "#2563eb"        # Modern Primary Blue
GOOD = "#059669"          # Emerald Green (fit >= 8)
WARN = "#d97706"          # Amber (fit 6-7)
MUTED = "#6b7280"         # Slate Grey
PURPLE_CHIP = "#7c3aed"    # Freelance / Contract Tag Accent

st.markdown(f"""
<style>
/* Emil Kowalski / Better UI Polish Variables */
:root {{
    --ease-out: cubic-bezier(0.23, 1, 0.32, 1);
    --ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);
}}

/* Base Theme & Card Styling */
.stApp {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}}

/* Button Polish (Interruptible, scale on active) */
div[data-testid="stButton"] button {{
    transition: transform 160ms var(--ease-out), background-color 160ms var(--ease-out) !important;
}}
div[data-testid="stButton"] button:active {{
    transform: scale(0.97) !important;
}}

/* Header Bar & Status Chips */
.jh-statuschip {{
    display: inline-flex; align-items: center; padding: 4px 14px;
    border-radius: 9999px; font-size: 0.83rem; font-weight: 500;
    background: #f3f4f6; border: 1px solid transparent; color: #374151;
    margin-right: 6px; margin-bottom: 6px;
    box-shadow: 0 1px 2px oklch(0 0 0 / 0.05); /* Depth over borders */
    transition: transform 160ms var(--ease-out), filter 160ms var(--ease-out);
}}
.jh-statuschip:hover {{
    transform: translateY(-1px);
    filter: brightness(0.97);
}}
.jh-statuschip b {{ margin-left: 5px; font-weight: 700; color: #111827; }}

/* Score Badges */
.jh-badge {{
    display: inline-block; min-width: 2.8em; text-align: center;
    padding: 4px 10px; border-radius: 9999px; font-weight: 800; font-size: 1.05rem;
    color: #ffffff; 
    box-shadow: 0 4px 12px oklch(0 0 0 / 0.12); /* Optical depth */
}}
.jh-badge.good {{ background: {GOOD}; }}
.jh-badge.warn {{ background: {WARN}; color: #ffffff; }}
.jh-badge.na   {{ background: #6b7280; }}

/* Tag Chips */
.jh-chip {{
    display: inline-block; padding: 2px 10px; margin-right: 6px; margin-bottom: 4px;
    border-radius: 9999px; font-size: 0.75rem; font-weight: 700;
    background: #eff6ff; color: {ACCENT}; border: 1px solid transparent;
    transition: transform 160ms var(--ease-out), filter 160ms var(--ease-out);
}}
.jh-chip:active {{
    transform: scale(0.97);
}}
.jh-chip.freelance {{
    background: #f5f3ff; color: {PURPLE_CHIP}; 
}}
.jh-chip.custom {{
    background: #eff6ff; color: #1d4ed8; 
}}
.jh-chip.geo-ok {{
    background: #ecfdf5; color: #047857; 
}}
.jh-chip.geo-warn {{
    background: #fffbeb; color: #b45309; 
}}
.jh-chip.feedback-bad {{
    background: #fef2f2; color: #dc2626; 
}}
.jh-chip.feedback-good {{
    background: #ecfdf5; color: #059669; 
}}

/* Card Typography & Meta */
.jh-title {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 4px; line-height: 1.35; }}
.jh-title a {{ text-decoration: none; color: #111827; transition: color 150ms var(--ease-out); }}
.jh-title a:hover {{ color: {ACCENT}; }}

.jh-meta {{ color: #6b7280; font-size: 0.85rem; margin-bottom: 8px; font-weight: 500; }}
.jh-summary {{ font-size: 0.94rem; color: #374151; margin-top: 6px; line-height: 1.45; }}
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


def is_freelance(row: pd.Series) -> bool:
    src = str(row.get("source", "")).lower()
    tags = str(row.get("tags", "")).lower()
    title = str(row.get("title", "")).lower()
    summary = str(row.get("summary", "")).lower()

    if any(k in src for k in ("upwork", "hacker news", "remoteok", "freelance", "contract")):
        return True
    if any(k in tags for k in ("freelance", "contract", "side_role")):
        return True
    if any(k in title or k in summary for k in ("freelance", "contractor", "contract role", "gig", "part-time", "part time", "fractional")):
        return True
    return False


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
    feedback_db = load_feedback()

    if not jobs:
        st.info("No results yet — run the pipeline.")
    else:
        df = pd.DataFrame(jobs)
        df["score"] = pd.to_numeric(df["score"], errors="coerce").fillna(0).astype(int)
        df["is_freelance"] = df.apply(is_freelance, axis=1)
        df["fb_cat"] = df["url"].map(lambda u: feedback_db.get(u, {}).get("category"))
        df["fb_label"] = df["url"].map(lambda u: feedback_db.get(u, {}).get("label"))
        df = df.sort_values(["found", "score"], ascending=[False, False])

        with st.sidebar:
            st.markdown("### Filters")
            min_score = st.slider("Min fit score", 0, 10, 0)
            job_type_filter = st.selectbox("Job Type", ["All Types", "Full-time Only", "Freelance / Contract Only"])
            hide_marked_bad = st.checkbox("Hide marked bad/irrelevant jobs", value=True)
            feedback_filter = st.selectbox(
                "Feedback Filter",
                ["All Jobs", "Unmarked Only", "Location Restricted", "Irrelevant Role", "Language Requirement", "Expired", "Good Fit"]
            )
            sources = st.multiselect("Source", sorted(df["source"].unique()))
            custom_only = st.checkbox("Custom-search results only")
            search = st.text_input("Search title / company / summary")
            max_cards = st.number_input("Cards shown", 10, 200, 40, step=10)

        view = df[df["score"] >= min_score]
        if job_type_filter == "Full-time Only":
            view = view[~view["is_freelance"]]
        elif job_type_filter == "Freelance / Contract Only":
            view = view[view["is_freelance"]]

        if hide_marked_bad:
            view = view[~view["fb_cat"].isin(["location_restricted", "irrelevant_role", "language_restricted", "expired"])]

        if feedback_filter == "Unmarked Only":
            view = view[view["fb_cat"].isna()]
        elif feedback_filter == "Location Restricted":
            view = view[view["fb_cat"] == "location_restricted"]
        elif feedback_filter == "Irrelevant Role":
            view = view[view["fb_cat"] == "irrelevant_role"]
        elif feedback_filter == "Language Requirement":
            view = view[view["fb_cat"] == "language_restricted"]
        elif feedback_filter == "Expired":
            view = view[view["fb_cat"] == "expired"]
        elif feedback_filter == "Good Fit":
            view = view[view["fb_cat"] == "good_fit"]

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

        st.caption(f"{len(view)} of {len(df)} jobs shown")
        for i, (_, row) in enumerate(view.head(int(max_cards)).iterrows()):
            score = int(row["score"])
            badge_cls = "good" if score >= 8 else ("warn" if score >= 6 else "na")
            summary, _, reason = (row.get("summary") or "").partition(" | ")

            # Build tag chips
            raw_tags = [t.strip() for t in (row.get("tags") or "").split(",") if t.strip()]
            chip_elements = []

            # Add User Feedback tag if marked
            fb_lbl = str(row["fb_label"]) if pd.notna(row.get("fb_label")) and str(row.get("fb_label")).strip() else None
            if fb_lbl:
                fb_cat = str(row.get("fb_cat") or "")
                chip_cls = "jh-chip feedback-good" if fb_cat == "good_fit" else "jh-chip feedback-bad"
                chip_elements.append(f'<span class="{chip_cls}">{html.escape(fb_lbl)}</span>')

            # Add explicit Freelance/Contract tag if detected
            if row["is_freelance"]:
                chip_elements.append('<span class="jh-chip freelance">⚡ FREELANCE / CONTRACT</span>')

            for t in raw_tags:
                if t.upper() in ("SIDE_ROLE", "FREELANCE", "CONTRACT") and row["is_freelance"]:
                    continue
                chip_cls = "jh-chip"
                if "CUSTOM" in t.upper():
                    chip_cls += " custom"
                elif "GEO" in t.upper() or "EGYPT" in t.upper():
                    chip_cls += " geo-ok" if "EGYPT" in t.upper() else " geo-warn"
                chip_elements.append(f'<span class="{chip_cls}">{html.escape(t)}</span>')

            chips_html = "".join(chip_elements)

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

                    fcol1, fcol2 = st.columns([3, 1])
                    with fcol1:
                        if reason:
                            with st.expander("Judge's reasoning"):
                                st.write(reason)
                    with fcol2:
                        u_key = f"{i}_{abs(hash(str(row['url'])))}"
                        with st.popover("💬 Feedback", key=f"pop_{u_key}"):
                            st.caption("Mark job feedback:")
                            curr_fb = row.get("fb_cat") or "none"
                            opts = [
                                ("None", "clear"),
                                ("📍 Location Restricted", "location_restricted"),
                                ("❌ Irrelevant Role", "irrelevant_role"),
                                ("🌐 Language Requirement", "language_restricted"),
                                ("⏰ Expired / Dead Link", "expired"),
                                ("👍 Good Fit / Applied", "good_fit"),
                            ]
                            idx = 0
                            for o_i, (_, cat_val) in enumerate(opts):
                                if cat_val == curr_fb:
                                    idx = o_i
                                    break

                            with st.form(key=f"fb_form_{u_key}", border=False):
                                selected_opt = st.radio(
                                    "Category",
                                    [o[0] for o in opts],
                                    index=idx,
                                    key=f"fb_radio_{u_key}"
                                )
                                submitted = st.form_submit_button("Save Feedback", use_container_width=True)
                                if submitted:
                                    target_cat = next(o[1] for o in opts if o[0] == selected_opt)
                                    save_feedback(row["url"], target_cat)
                                    for k in list(st.session_state.keys()):
                                        if "fb_" in str(k) or "pop_" in str(k):
                                            del st.session_state[k]
                                    st.toast("Feedback saved!")
                                    time.sleep(0.2)
                                    st.rerun()

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
