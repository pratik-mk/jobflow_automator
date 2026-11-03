import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.config import (BASELINE_FILE, PROMPTS_DIR, load_candidate, load_settings,  # noqa: E402
                         save_candidate, save_tunables)
from core.models import Status, now_iso  # noqa: E402
from core.store import get_store  # noqa: E402

st.set_page_config(page_title="JobFlow", page_icon=None, layout="wide", initial_sidebar_state="collapsed")

LABEL = Status.LABELS
TABLE_COLS = ["id", "status", "posted", "days_old", "fit_score", "company_rating", "ats_match", "files", "company",
              "title", "company_type", "work_mode", "location", "source", "date_posted", "date_scraped",
              "date_applied", "url", "notes"]
AGE_BUCKETS = ["< 24h", "1-5 days", "5-7 days", "Older", "Unknown"]
AGE_COLORS = ["#16a34a", "#2563eb", "#d97706", "#6b7280", "#9ca3af"]
SORTS = {"Best match": (["fit_score", "company_rating"], False), "Newest first": (["days_old", "fit_score"], [True, False]),
         "Company rating": (["company_rating", "fit_score"], False), "ATS match": (["ats_match", "fit_score"], False)}


def age_bucket(days) -> str:
    if pd.isna(days):
        return "Unknown"
    if days < 1:
        return "< 24h"
    if days <= 5:
        return "1-5 days"
    if days <= 7:
        return "5-7 days"
    return "Older"


# ---------- data ----------

@st.cache_resource
def store():
    return get_store(load_settings())


@st.cache_data(ttl=120, show_spinner="Loading jobs...")
def jobs_df() -> pd.DataFrame:
    df = pd.DataFrame([j.to_dict() for j in store().list_jobs()])
    if df.empty:
        return pd.DataFrame(columns=TABLE_COLS)
    for c in ("fit_score", "company_rating", "ats_match"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    posted = pd.to_datetime(df["date_posted"], errors="coerce")
    scraped = pd.to_datetime(df["date_scraped"], errors="coerce").dt.normalize()
    df["days_old"] = (pd.Timestamp.now().normalize() - posted.fillna(scraped)).dt.days
    df["posted"] = [[age_bucket(d)] for d in df["days_old"]]
    has = lambda p: bool(p) and Path(p).exists()  # noqa: E731
    df["files"] = [" + ".join(n for n, ok in (("Resume", has(r)), ("Cover", has(c))) if ok)
                   for r, c in zip(df["resume_path"], df["cover_letter_path"])]
    return df


def refresh():
    jobs_df.clear()


def update_status(job_id: str, status: str, notes: str | None = None):
    changes = {"status": status}
    if status == Status.APPLIED:
        changes["date_applied"] = now_iso()[:10]
    if notes is not None:
        changes["notes"] = notes
    store().update_job(job_id, **changes)


# ---------- background tasks ----------

TASK_NAMES = {"search": "Search fresh jobs", "build": "Build resumes", "rate": "Re-rate jobs",
              "refilter": "Re-apply rules", "cover": "Write cover letter"}


def run_task(command: str, ids: list[str] | None = None, extra: list[str] | None = None):
    (ROOT / "logs").mkdir(exist_ok=True)
    log_path = ROOT / "logs" / f"task_{command}.log"
    cmd = [sys.executable, "-u", str(ROOT / "cli.py"), command] + (["--ids", *ids] if ids else []) + (extra or [])
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=open(log_path, "w"), stderr=subprocess.STDOUT)
    st.session_state.setdefault("tasks", []).append({"command": command, "proc": proc, "log": log_path, "reported": False})
    st.toast(f"Started: {TASK_NAMES.get(command, command)}")


def _clean_log(path: Path, lines: int = 30) -> str:
    if not path.exists():
        return "(starting...)"
    out = []
    for line in path.read_text(errors="ignore").splitlines():
        if "WARNING" in line and "streamlit" in line.lower():
            continue
        parts = line.split(" ", 3)
        out.append(f"{parts[1][:8]}  {parts[3]}" if len(parts) == 4 and parts[0][:2] == "20" else line)
    return "\n".join(out[-lines:]) or "(starting...)"


@st.fragment(run_every=2)
def activity_panel():
    tasks = st.session_state.get("tasks", [])
    if not tasks:
        return
    running = [TASK_NAMES.get(t["command"], t["command"]) for t in tasks if t["proc"].poll() is None]
    if running:
        st.markdown(
            f"""<style>
            .jf-busy {{position: fixed; top: 60px; right: 20px; z-index: 1000; display: flex; align-items: center;
              gap: 8px; padding: 6px 12px; border-radius: 999px; font-size: 13px;
              background: rgba(37, 99, 235, .95); color: #fff; box-shadow: 0 2px 8px rgba(0,0,0,.3);}}
            .jf-spin {{width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.35); border-top-color: #fff;
              border-radius: 50%; animation: jfspin .8s linear infinite;}}
            @keyframes jfspin {{to {{transform: rotate(360deg);}}}}
            </style>
            <div class="jf-busy"><div class="jf-spin"></div>{" + ".join(running)}...</div>""",
            unsafe_allow_html=True,
        )
    st.divider()
    st.markdown("##### Activity")
    finished_now = False
    for t in reversed(tasks[-3:]):
        name = TASK_NAMES.get(t["command"], t["command"])
        code = t["proc"].poll()
        if code is None:
            st.info(f"Running: **{name}**", icon=None)
        elif code == 0:
            st.success(f"Finished: **{name}**")
        else:
            st.error(f"Failed: **{name}** (full log: logs/{t['log'].name})")
        st.code(_clean_log(t["log"]), language=None)
        if code is not None and not t["reported"]:
            t["reported"] = True
            finished_now = True
    if finished_now:
        refresh()
        st.rerun(scope="app")


def tasks_panel():
    """Kept for call sites; live progress is shown by activity_panel at the bottom of every page."""


# ---------- pages ----------

def page_dashboard():
    st.title("JobFlow")
    df = jobs_df()
    counts = df["status"].value_counts()
    m = st.columns(6)
    m[0].metric("New", int(counts.get(Status.NEW, 0)))
    m[1].metric("Shortlisted", int(counts.get(Status.SHORTLISTED, 0)))
    m[2].metric("Resume ready", int(counts.get(Status.RESUME_READY, 0)))
    m[3].metric("Applied", int(counts.get(Status.APPLIED, 0)))
    m[4].metric("Calls / interviews", int(counts.get(Status.RECRUITER_CALL, 0) + counts.get(Status.INTERVIEWING, 0)))
    m[5].metric("Offers", int(counts.get(Status.OFFER, 0)))

    st.write("")
    a, b, c = st.columns([2, 2, 1])
    if a.button("Search fresh jobs", type="primary", width="stretch",
                help="Scrape every enabled source, then rate new jobs (fit + company)"):
        run_task("search")
    shortlisted = int(counts.get(Status.SHORTLISTED, 0))
    if b.button(f"Build resumes for shortlisted ({shortlisted})", width="stretch", disabled=not shortlisted):
        run_task("build")
    if c.button("Refresh", width="stretch"):
        refresh()
        st.rerun()
    tasks_panel()

    st.subheader("Work queue")
    views = {
        "Best matches (shortlisted + resume ready)": [Status.SHORTLISTED, Status.RESUME_READY],
        "New (not rated yet)": [Status.NEW],
        "Not a fit (review and shortlist manually)": [Status.NOT_A_FIT],
        "Applied and in progress": Status.PIPELINE,
    }
    choice = st.segmented_control("Show", list(views), default=list(views)[0], label_visibility="collapsed")
    queue = df[df["status"].isin(views[choice or list(views)[0]])]
    if queue.empty:
        st.caption("Nothing here yet - click Search fresh jobs.")
    else:
        job_table(queue, key="dash", height=420,
                  columns=["id", "status", "posted", "days_old", "fit_score", "company_rating", "ats_match", "files",
                           "company", "title",
                           "company_type", "work_mode", "date_posted", "url", "notes"])

    s = load_settings()
    if s.sheet_url:
        st.caption(f"Data is saved to Google Sheets and SQLite - [open the Google Sheet]({s.sheet_url})")


def page_jobs():
    st.title("Jobs")
    df = jobs_df()
    if df.empty:
        st.info("No jobs yet. Use Search fresh jobs on the Dashboard.")
        return

    f = st.columns([3, 1, 1, 2, 2])
    default = [s for s in Status.ALL if s not in (Status.NOT_A_FIT, Status.SKIPPED, Status.WITHDRAWN)]
    statuses = f[0].multiselect("Status", Status.ALL, default=default, format_func=LABEL.get)
    min_fit = f[1].number_input("Min fit", 0, 100, 0, step=5)
    min_rating = f[2].number_input("Min company", 0, 100, 0, step=5)
    types = f[3].multiselect("Company type", sorted(t for t in df["company_type"].dropna().unique() if t))
    text = f[4].text_input("Search", placeholder="company or title")

    g = st.columns([2, 6])
    sources = g[0].multiselect("Source", sorted(s for s in df["source"].dropna().unique() if s))

    view = df[df["status"].isin(statuses)]
    if min_fit:
        view = view[view["fit_score"].fillna(0) >= min_fit]
    if min_rating:
        view = view[view["company_rating"].fillna(0) >= min_rating]
    if types:
        view = view[view["company_type"].isin(types)]
    if sources:
        view = view[view["source"].isin(sources)]
    if text:
        view = view[view["company"].str.contains(text, case=False, na=False) | view["title"].str.contains(text, case=False, na=False)]

    job_table(view, key="jobs", height=520)


def job_table(view: pd.DataFrame, key: str, height: int = 420, columns: list[str] | None = None):
    """Editable job table: change Status/Notes inline, tick rows to build resumes or cover letters."""
    cols = columns or TABLE_COLS
    t = st.columns([3, 1])
    ages = t[0].pills("Posted", AGE_BUCKETS[:-1], selection_mode="multi", key=f"{key}_age",
                      help="Filter by how long ago the job was posted")
    sort = t[1].selectbox("Sort", list(SORTS), key=f"{key}_sort")
    if ages:
        view = view[view["posted"].map(lambda v: v[0] in ages)]
    by, asc = SORTS[sort]
    view = view.sort_values(by, ascending=asc, na_position="last")[cols].copy()
    view.insert(0, "select", False)
    st.caption(f"{len(view)} jobs - edit Status or Notes in the table and click Save changes; "
               "tick rows to build a resume or cover letter.")
    edited = st.data_editor(
        view, hide_index=True, width="stretch", height=height, key=f"{key}_editor",
        disabled=[c for c in view.columns if c not in ("select", "status", "notes")],
        column_config={
            "id": None,
            "select": st.column_config.CheckboxColumn("", width="small"),
            "status": st.column_config.SelectboxColumn("Status", options=Status.ALL, required=True, width="medium"),
            "posted": st.column_config.MultiselectColumn("Posted", options=AGE_BUCKETS, color=AGE_COLORS, width="small",
                                                         help="Age of the posting (falls back to scrape date)"),
            "days_old": st.column_config.NumberColumn("Days", format="%d", width="small",
                                                      help="Days since posted - click the header to sort"),
            "fit_score": st.column_config.ProgressColumn("Fit", min_value=0, max_value=100, format="%d"),
            "company_rating": st.column_config.ProgressColumn("Company", min_value=0, max_value=100, format="%d"),
            "ats_match": st.column_config.NumberColumn("ATS %"),
            "files": st.column_config.TextColumn("Files", help="Resume / cover letter generated"),
            "url": st.column_config.LinkColumn("Link", display_text="Open"),
            "notes": st.column_config.TextColumn("Notes", width="medium"),
        },
    )

    picked = edited[edited["select"]]["id"].tolist()
    b = st.columns([1.2, 1.2, 1.2, 1, 2.4])
    if b[0].button("Save changes", type="primary", key=f"{key}_save", width="stretch"):
        before = view.set_index("id")
        changed = 0
        for row in edited.to_dict(orient="records"):
            old = before.loc[row["id"]]
            if row["status"] != old["status"] or (row["notes"] or "") != (old["notes"] or ""):
                update_status(row["id"], row["status"], row["notes"] or "")
                changed += 1
        refresh()
        st.toast(f"Saved {changed} change(s)")
        st.rerun()
    if b[1].button(f"Build resume ({len(picked)})", disabled=not picked, key=f"{key}_build", width="stretch"):
        run_task("build", picked)
    if b[2].button(f"Cover letter ({len(picked)})", disabled=not picked, key=f"{key}_cover", width="stretch",
                   help="Write a cover letter for each ticked job, saved in its company folder"):
        run_task("cover", picked)
    if b[3].button(f"Re-rate ({len(picked)})", disabled=not picked, key=f"{key}_rate", width="stretch"):
        run_task("rate", picked)


def page_job():
    st.title("Job")
    df = jobs_df()
    if df.empty:
        st.info("No jobs yet.")
        return
    df = df.sort_values(["fit_score"], ascending=False)
    labels = {r.id: f"{r.company} - {r.title}  [{LABEL.get(r.status, r.status)}]" for r in df.itertuples()}
    jid = st.selectbox("Job", list(labels), format_func=labels.get)
    job = store().get_job(jid)
    if not job:
        return

    st.markdown(f"### {job.title}\n**{job.company}** | {job.location or '-'} | {job.work_mode or '-'} | "
                f"[Open posting]({job.url})")
    m = st.columns(5)
    m[0].metric("Fit", job.fit_score if job.fit_score is not None else "-")
    m[1].metric("Company rating", job.company_rating if job.company_rating is not None else "-")
    m[2].metric("Company type", job.company_type or "-")
    m[3].metric("ATS match", f"{job.ats_match}%" if job.ats_match is not None else "-")
    m[4].metric("Posted", job.date_posted or "-")
    st.caption(f"Source: {job.source} | Scraped: {job.date_scraped} | Applied: {job.date_applied or '-'} | {job.salary}")
    if job.score_reason:
        st.write(f"**Why:** {job.score_reason}")
    st.write(f"**You match:** {job.matched_skills or '-'}  \n**Gaps:** {job.missing_skills or '-'}")

    left, right = st.columns(2)
    with left:
        with st.form("status"):
            status = st.selectbox("Status", Status.ALL, index=Status.ALL.index(job.status), format_func=LABEL.get)
            notes = st.text_area("Notes", job.notes, placeholder="e.g. recruiter name, interview date, feedback")
            if st.form_submit_button("Save", type="primary"):
                update_status(job.id, status, notes)
                refresh()
                st.success("Saved")
    with right:
        st.write("**Tailored resume**")
        if job.resume_path and Path(job.resume_path).exists():
            st.download_button("Download PDF", Path(job.resume_path).read_bytes(), file_name=Path(job.resume_path).name,
                               mime="application/pdf", type="primary")
            st.caption(job.resume_path)
            if job.resume_keywords:
                st.caption(job.resume_keywords)
        if st.button("Rebuild resume" if job.resume_path else "Build resume"):
            run_task("build", [job.id])
        tasks_panel()

    cover_letter_section(job)

    with st.expander("Job description"):
        st.text(job.description)


def cover_letter_section(job):
    from services import cover_letter as cl
    st.divider()
    st.subheader("Cover letter")
    txt = cl.text_path(load_settings(), job)
    has_letter = bool(job.cover_letter_path and Path(job.cover_letter_path).exists() and txt.exists())

    notes = st.text_input("Notes for the letter (optional)", key=f"cl_notes_{job.id}",
                          placeholder="e.g. Hiring manager: Priya Sharma; referred by Rahul; keep it short and warm")
    if st.button("Regenerate cover letter" if has_letter else "Generate cover letter",
                 type="secondary" if has_letter else "primary"):
        run_task("cover", [job.id], ["--notes", notes] if notes else None)

    if has_letter:
        text = st.text_area("Edit the letter (blank lines separate paragraphs)", txt.read_text(encoding="utf-8"),
                            height=380, key=f"cl_text_{job.id}")
        c = st.columns([1, 1, 1, 3])
        if c[0].button("Save edits"):
            pdf = cl.render_pdf(load_settings(), job, cl.from_text(text))
            store().update_job(job.id, cover_letter_path=pdf)
            st.success("Saved and PDF updated")
        c[1].download_button("Download PDF", Path(job.cover_letter_path).read_bytes(),
                             file_name=Path(job.cover_letter_path).name, mime="application/pdf")
        c[2].download_button("Download .txt", text, file_name=txt.name, mime="text/plain")
        st.caption("Copy-paste version (use the copy icon):")
        st.code(text, language=None, wrap_lines=True)
    else:
        st.caption("Uses your baseline resume and this job description. Takes about 20 seconds; "
                   "progress shows in Activity below.")


def page_settings():
    st.title("Settings")
    settings = load_settings()
    t = settings.tunables
    js = t.setdefault("sources", {}).setdefault("jobspy", {"enabled": True})
    search, filters, rating, resume = (t.setdefault(k, {}) for k in ("search", "filters", "rating", "resume"))

    def lines(label, values, key, help=None):
        return [v.strip() for v in st.text_area(label, "\n".join(values), key=key, help=help or "One per line").splitlines() if v.strip()]

    with st.form("settings"):
        st.subheader("Job search")
        js["terms"] = lines("Search terms", js.get("terms", []), "terms")
        c = st.columns(4)
        js["location"] = c[0].text_input("Location", js.get("location", ""))
        windows = {24: "Last 24 hours", 72: "Last 3 days", 168: "Last 7 days", 336: "Last 14 days", 720: "Last 30 days"}
        cur = search.get("posted_within_hours", 24)
        search["posted_within_hours"] = c[1].selectbox("Posted within", list(windows), format_func=windows.get,
                                                       index=list(windows).index(cur) if cur in windows else 0)
        types = ["", "fulltime", "parttime", "contract", "internship"]
        js["job_type"] = c[2].selectbox("Job type", types, index=types.index(js.get("job_type", "")),
                                        format_func=lambda v: v or "Any")
        js["results_wanted"] = c[3].number_input("Results per site per term", 5, 200, js.get("results_wanted", 20), step=5)
        c = st.columns([3, 1, 1])
        js["sites"] = c[0].multiselect("Sites", ["linkedin", "naukri", "indeed", "glassdoor", "google"], js.get("sites", []))
        js["remote_only"] = c[1].toggle("Remote only", js.get("remote_only", False))
        js["enabled"] = c[2].toggle("Source enabled", js.get("enabled", True))

        st.subheader("Company career boards")
        st.caption("Jobs straight from company sites (Workday, Greenhouse, Lever, Ashby) - NVIDIA, Salesforce, Adobe, "
                   "Mastercard, Stripe, Databricks, OpenAI and more. Reliable, with real posting dates.")
        cb = t["sources"].setdefault("company_boards", {"enabled": False})
        c = st.columns([1, 1, 1, 3])
        cb["enabled"] = c[0].toggle("Enabled", cb.get("enabled", False), key="cb_on")
        cb["max_age_days"] = c[1].number_input("Max age (days)", 1, 60, cb.get("max_age_days", 14))
        cb["max_per_company"] = c[2].number_input("Max jobs per company", 1, 50, cb.get("max_per_company", 8))
        cb["locations"] = [x.strip().lower() for x in c[3].text_input(
            "Location must contain one of", ", ".join(cb.get("locations", ["bangalore", "bengaluru", "india"])),
            help="Comma separated; matched against the job's location").split(",") if x.strip()]
        with st.expander(f"Companies ({len(cb.get('workday', []))} Workday, {len(cb.get('greenhouse', {}))} Greenhouse, "
                         f"{len(cb.get('lever', {}))} Lever, {len(cb.get('ashby', {}))} Ashby)"):
            st.caption("Add a company by its board ID: boards.greenhouse.io/<id>, jobs.lever.co/<id>, "
                       "jobs.ashbyhq.com/<id>, or the full Workday careers URL (https://<tenant>.wdN.myworkdayjobs.com/<site>).")
            companies_raw = st.text_area("Company lists (JSON)", json.dumps(
                {k: cb.get(k, {} if k != "workday" else []) for k in ("workday", "greenhouse", "lever", "ashby")}, indent=2),
                height=320)

        st.subheader("Shortlist rules")
        c = st.columns(3)
        rating["min_fit_score"] = c[0].slider("Min fit score", 0, 100, rating.get("min_fit_score", 70), step=5)
        rating["min_company_rating"] = c[1].slider("Min company rating", 0, 100, rating.get("min_company_rating", 60), step=5)
        modes = rating.get("work_modes", ["any", "remote", "hybrid", "onsite"])
        rating["work_mode"] = c[2].selectbox("Work mode", modes, index=modes.index(rating.get("work_mode", "any")))
        rating["allowed_company_types"] = st.multiselect(
            "Company types to shortlist", rating.get("company_types", []), rating.get("allowed_company_types", []),
            help="product, startup, mnc, big_tech, fintech, consulting, it_services, staffing")

        st.subheader("Title filters")
        c = st.columns(2)
        with c[0]:
            filters["include_title_keywords"] = lines("Title must contain one of", filters.get("include_title_keywords", []), "inc")
        with c[1]:
            filters["exclude_title_keywords"] = lines("Skip titles containing", filters.get("exclude_title_keywords", []), "exc")
        c = st.columns(3)
        filters["min_description_chars"] = c[0].number_input("Min description length", 0, 5000, filters.get("min_description_chars", 500), step=100)
        filters["max_per_company"] = c[1].number_input("Max jobs per company per search", 1, 20, filters.get("max_per_company", 2))
        resume["max_per_run"] = c[2].number_input("Max resumes per build", 1, 50, resume.get("max_per_run", 10))

        st.subheader("Resume tailoring")
        modes = {"flexible": "Flexible - reshape your real projects around each JD (recommended)",
                 "strict": "Strict - stay close to the baseline wording"}
        cur_mode = resume.get("tailoring_mode", "flexible")
        resume["tailoring_mode"] = st.radio("Tailoring mode", list(modes), format_func=modes.get,
                                            index=list(modes).index(cur_mode) if cur_mode in modes else 0)

        saved = st.form_submit_button("Save settings", type="primary")
    if saved:
        try:
            cb.update(json.loads(companies_raw))
        except json.JSONDecodeError as e:
            st.error(f"Company lists are not valid JSON: {e}")
            return
        save_tunables(t)
        st.success("Saved. New searches use these settings.")
    if st.button("Re-apply shortlist rules to rated jobs", help="No AI calls - just re-checks scores against the rules"):
        run_task("refilter")
    tasks_panel()


def page_baseline():
    st.title("Resume baseline")
    st.caption("Tailored resumes only use facts from here. Add projects, metrics and skills to make them stronger.")
    tab1, tab2, tab3 = st.tabs(["Experience and skills", "Header, roles and education", "Tailoring prompt"])
    with tab1:
        text = st.text_area("Baseline resume (markdown)", BASELINE_FILE.read_text(encoding="utf-8"), height=600)
        if st.button("Save baseline", type="primary"):
            BASELINE_FILE.write_text(text, encoding="utf-8")
            st.success("Saved")
    with tab2:
        st.caption("Fixed details printed on every resume: contact header, job titles and dates, education, "
                   "certifications, achievements.")
        raw = st.text_area("candidate.json", json.dumps(load_candidate(), indent=2, ensure_ascii=False), height=600)
        if st.button("Save details", type="primary"):
            try:
                save_candidate(json.loads(raw))
                st.success("Saved")
            except json.JSONDecodeError as e:
                st.error(f"Invalid JSON: {e}")
    with tab3:
        path = PROMPTS_DIR / "resume.md"
        prompt = st.text_area("Instructions given to the AI when tailoring", path.read_text(encoding="utf-8"), height=500)
        if st.button("Save prompt", type="primary"):
            path.write_text(prompt, encoding="utf-8")
            st.success("Saved")


nav = st.navigation(
    [
        st.Page(page_dashboard, title="Dashboard", url_path="dashboard", default=True),
        st.Page(page_jobs, title="Jobs", url_path="jobs"),
        st.Page(page_job, title="Job", url_path="job"),
        st.Page(page_settings, title="Settings", url_path="settings"),
        st.Page(page_baseline, title="Resume baseline", url_path="baseline"),
    ],
    position="top",
)
nav.run()
activity_panel()
