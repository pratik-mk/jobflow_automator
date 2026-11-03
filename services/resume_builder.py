import logging
import os
import re
import subprocess

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from pydantic import BaseModel, Field

from core.config import load_baseline, load_candidate, load_prompt
from core.llm import ask_json
from core.models import Job, Status

log = logging.getLogger(__name__)

LATEX_SPECIAL = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"$\sim$", "^": r"\textasciicircum{}",
    "<": r"\textless{}", ">": r"\textgreater{}",
    "\u2014": "---", "\u2013": "--", "\u2019": "'", "\u2018": "`", "\u201c": "``", "\u201d": "''",
    "\u2026": "...", "\u00a0": " ",
}
NUMBER = re.compile(r"\d+(?:\.\d+)?")


class SkillGroup(BaseModel):
    category: str
    items: str


class RoleBullets(BaseModel):
    key: str
    bullets: list[str] = Field(min_length=2, max_length=8)


class Project(BaseModel):
    name: str
    link: str = ""
    year: str = ""
    description: str


class TailoredResume(BaseModel):
    headline: str
    summary: str
    roles: list[RoleBullets]
    skills: list[SkillGroup] = Field(min_length=3, max_length=7)
    projects: list[Project] = Field(min_length=1, max_length=4)
    matched_keywords: list[str] = []
    missing_keywords: list[str] = []


def latex_escape(text: str) -> str:
    return "".join(LATEX_SPECIAL.get(ch, ch) for ch in str(text))


def latex_bold(text: str) -> str:
    return re.sub(r"\*\*(.+?)\*\*", lambda m: r"\textbf{" + m.group(1) + "}", latex_escape(text))


def _env(settings) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(settings.templates_dir)),
        block_start_string=r"\BLOCK{", block_end_string="}",
        variable_start_string=r"\VAR{", variable_end_string="}",
        comment_start_string=r"\#{", comment_end_string="}",
        trim_blocks=True, autoescape=False, undefined=StrictUndefined,
    )
    env.filters["e"] = latex_escape
    env.filters["bold"] = latex_bold
    return env


def _slug(text: str, limit: int = 60) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:limit] or "Unknown"


def _invented_numbers(resume: TailoredResume, baseline: str) -> set[str]:
    """Numbers in the tailored text that never appear in the baseline (likely fabricated metrics)."""
    allowed = set(NUMBER.findall(baseline)) | {"1", "2", "3"}
    text = " ".join([resume.summary, *(b for r in resume.roles for b in r.bullets), *(p.description for p in resume.projects)])
    return {n for n in NUMBER.findall(text) if n not in allowed}


MODES = {
    "strict": "\n\nTAILORING MODE: STRICT. Stay close to the baseline wording; only reorder, select and rephrase.",
    "flexible": (
        "\n\nTAILORING MODE: FLEXIBLE. You may reshape the candidate's real projects around what this JD emphasises: "
        "describe the same work in the JD's vocabulary, highlight the aspects of it the JD cares about (scale, "
        "reliability, APIs, data, AI, frontend, ownership, mentoring), and mention adjacent tools or practices that "
        "naturally accompany the listed work (e.g. microservices, CI/CD, unit testing, code reviews, monitoring) when "
        "the candidate could credibly discuss them in an interview. Still never invent employers, titles, dates, "
        "degrees, certifications, metrics, or whole projects that do not exist in the baseline."
    ),
}


def tailor(settings, job: Job) -> TailoredResume:
    baseline = load_baseline()
    candidate = load_candidate()
    mode = settings.section("resume").get("tailoring_mode", "flexible")
    system = load_prompt("resume") + MODES.get(mode, MODES["flexible"])
    role_keys = ", ".join(f'"{r["key"]}" ({r["title"]} at {r["company"]}, {r["dates"]})' for r in candidate["roles"])
    user = (f"BASELINE RESUME:\n{baseline}\n\nRole keys to write bullets for: {role_keys}\n\n"
            f"JOB: {job.title} at {job.company} ({job.location})\n\nJOB DESCRIPTION:\n{job.description[:10000]}")
    resume = ask_json(settings, system, user, TailoredResume)
    invented = _invented_numbers(resume, baseline)
    if invented:
        log.warning("Draft used numbers not in your baseline %s - regenerating without them", sorted(invented))
        user += (f"\n\nIMPORTANT: a previous draft used these numbers that are NOT in the baseline: {sorted(invented)}. "
                 "Remove or replace them with baseline facts.")
        resume = ask_json(settings, system, user, TailoredResume)
    return resume


def ats_match(resume: TailoredResume) -> int | None:
    total = len(resume.matched_keywords) + len(resume.missing_keywords)
    return round(100 * len(resume.matched_keywords) / total) if total else None


def compile_resume(settings, job: Job, resume: TailoredResume) -> str:
    candidate = load_candidate()
    bullets = {r.key: r.bullets for r in resume.roles}
    roles = [{**r, "bullets": bullets.get(r["key"], [])} for r in candidate["roles"]]
    tex = _env(settings).get_template("resume_template.tex").render(c=candidate, r=resume, roles=roles)

    company_dir = settings.output_dir / _slug(job.company)
    company_dir.mkdir(parents=True, exist_ok=True)
    jobname = f"{_slug(candidate['name'], 30)}_{_slug(job.title, 60)}"
    tex_path = company_dir / f"{jobname}.tex"
    tex_path.write_text(tex, encoding="utf-8")

    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={company_dir}", str(tex_path)],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "TEXINPUTS": f"{settings.templates_dir}{os.pathsep}"},
    )
    pdf_path = company_dir / f"{jobname}.pdf"
    if proc.returncode != 0 or not pdf_path.exists():
        raise RuntimeError(f"pdflatex failed for {jobname}:\n{proc.stdout[-2000:]}")
    for ext in (".aux", ".log", ".out"):
        (company_dir / f"{jobname}{ext}").unlink(missing_ok=True)
    return str(pdf_path)


def build(settings, store, job_ids: list[str] | None = None) -> list[Job]:
    if job_ids:
        jobs = [j for j in (store.get_job(i) for i in job_ids) if j]
    else:
        jobs = store.list_jobs([Status.SHORTLISTED])[: settings.section("resume").get("max_per_run", 10)]
    built = []
    log.info("Building %d resume(s)", len(jobs))
    for n, job in enumerate(jobs, 1):
        log.info("[%d/%d] %s - %s: tailoring content with AI...", n, len(jobs), job.company, job.title)
        try:
            resume = tailor(settings, job)
            log.info("[%d/%d] content ready (%d keywords matched, %d gaps) - compiling PDF...", n, len(jobs),
                     len(resume.matched_keywords), len(resume.missing_keywords))
            pdf = compile_resume(settings, job, resume)
        except Exception as e:
            log.exception("[%d/%d] FAILED for %s: %s", n, len(jobs), job.company, e)
            store.update_job(job.id, notes=f"resume error: {str(e)[:300]}")
            continue
        log.info("[%d/%d] done: %s (ATS match %s%%)", n, len(jobs), pdf, ats_match(resume))
        changes = {
            "resume_path": pdf, "ats_match": ats_match(resume),
            "resume_keywords": f"matched: {', '.join(resume.matched_keywords)} | missing: {', '.join(resume.missing_keywords)}",
        }
        if job.status in (Status.NEW, Status.SHORTLISTED, Status.NOT_A_FIT):
            changes["status"] = Status.RESUME_READY
        store.update_job(job.id, **changes)
        for k, v in changes.items():
            setattr(job, k, v)
        built.append(job)
    return built
