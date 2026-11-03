import logging
import os
import subprocess
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from core.config import load_baseline, load_candidate, load_prompt
from core.llm import ask_json
from core.models import Job
from services.resume_builder import _env, _slug

log = logging.getLogger(__name__)


class CoverLetter(BaseModel):
    greeting: str
    paragraphs: list[str] = Field(min_length=1, max_length=6)
    closing: str = "Sincerely,"


def _base_path(settings, job: Job) -> Path:
    folder = settings.output_dir / _slug(job.company)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{_slug(load_candidate()['name'], 30)}_Cover_Letter_{_slug(job.title, 60)}"


def text_path(settings, job: Job) -> Path:
    if job.cover_letter_path:
        return Path(job.cover_letter_path).with_suffix(".txt")
    return _base_path(settings, job).with_suffix(".txt")


def to_text(letter: CoverLetter) -> str:
    return "\n\n".join([letter.greeting, *letter.paragraphs, letter.closing])


def from_text(text: str) -> CoverLetter:
    """Parse an edited plain-text letter: first block is the greeting, a short last block is the closing."""
    blocks = [b.strip() for b in text.strip().split("\n\n") if b.strip()]
    greeting = blocks.pop(0) if blocks and len(blocks[0]) < 60 else "Dear Hiring Manager,"
    closing = blocks.pop() if blocks and len(blocks[-1]) < 40 else "Sincerely,"
    return CoverLetter(greeting=greeting, paragraphs=blocks or [""], closing=closing)


def generate(settings, job: Job, notes: str = "") -> CoverLetter:
    log.info("Writing cover letter for %s - %s...", job.company, job.title)
    user = (f"BASELINE RESUME:\n{load_baseline()}\n\nJOB: {job.title} at {job.company} ({job.location})\n\n"
            f"JOB DESCRIPTION:\n{job.description[:9000]}\n\nCANDIDATE NOTES:\n{notes or '(none)'}")
    return ask_json(settings, load_prompt("cover_letter"), user, CoverLetter)


def render_pdf(settings, job: Job, letter: CoverLetter) -> str:
    base = _base_path(settings, job)
    tex = _env(settings).get_template("cover_letter.tex").render(
        c=load_candidate(), date=date.today().strftime("%d %B %Y"), company=job.company, role=job.title,
        greeting=letter.greeting, paragraphs=[p for p in letter.paragraphs if p.strip()], closing=letter.closing,
    )
    base.with_suffix(".tex").write_text(tex, encoding="utf-8")
    base.with_suffix(".txt").write_text(to_text(letter), encoding="utf-8")
    proc = subprocess.run(
        ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", f"-output-directory={base.parent}",
         str(base.with_suffix(".tex"))],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "TEXINPUTS": f"{settings.templates_dir}{os.pathsep}"},
    )
    pdf = base.with_suffix(".pdf")
    if proc.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"pdflatex failed for cover letter:\n{proc.stdout[-1500:]}")
    for ext in (".aux", ".log", ".out", ".tex"):
        base.with_suffix(ext).unlink(missing_ok=True)
    log.info("Cover letter saved: %s", pdf)
    return str(pdf)


def build(settings, store, job_id: str, notes: str = "") -> str:
    job = store.get_job(job_id)
    if not job:
        raise ValueError(f"job {job_id} not found")
    pdf = render_pdf(settings, job, generate(settings, job, notes))
    store.update_job(job.id, cover_letter_path=pdf)
    return pdf
