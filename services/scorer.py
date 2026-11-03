import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from core.config import load_baseline, load_prompt
from core.llm import ask_json
from core.models import Job, Status

log = logging.getLogger(__name__)

CompanyType = Literal["product", "startup", "mnc", "big_tech", "fintech", "consulting", "it_services", "staffing"]
WorkMode = Literal["remote", "hybrid", "onsite", "unknown"]


class JobRating(BaseModel):
    id: str
    fit_score: int = Field(ge=0, le=100)
    company_rating: int = Field(ge=0, le=100)
    company_type: CompanyType
    work_mode: WorkMode
    reason: str
    matched_skills: list[str] = []
    missing_skills: list[str] = []


class RatingBatch(BaseModel):
    ratings: list[JobRating]


def _payload(job: Job) -> dict:
    return {"id": job.id, "company": job.company, "title": job.title, "location": job.location,
            "company_info": job.company_info, "salary": job.salary, "description": job.description[:5000]}


def passes_filters(job: Job, cfg: dict) -> bool:
    if (job.fit_score or 0) < cfg.get("min_fit_score", 70):
        return False
    if (job.company_rating or 0) < cfg.get("min_company_rating", 60):
        return False
    allowed = cfg.get("allowed_company_types") or []
    if allowed and job.company_type not in allowed:
        return False
    mode = cfg.get("work_mode", "any")
    return mode == "any" or job.work_mode in (mode, "unknown", "")


def rate(settings, store, job_ids: list[str] | None = None) -> list[Job]:
    cfg = settings.section("rating")
    if job_ids:
        jobs = [j for j in (store.get_job(i) for i in job_ids) if j]
    else:
        jobs = store.list_jobs([Status.NEW])[: cfg.get("max_jobs_per_run", 40)]
    if not jobs:
        return []

    baseline = load_baseline()[:7000]
    size = cfg.get("batch_size", 5)
    rated: list[Job] = []
    for i in range(0, len(jobs), size):
        batch = jobs[i:i + size]
        user = f"Candidate baseline resume:\n{baseline}\n\nJobs:\n{json.dumps([_payload(j) for j in batch], indent=2)}"
        try:
            result = ask_json(settings, load_prompt("score"), user, RatingBatch)
        except Exception as e:
            log.error("Rating batch failed: %s", e)
            continue
        by_id = {r.id: r for r in result.ratings}
        for job in batch:
            r = by_id.get(job.id)
            if not r:
                continue
            job.fit_score, job.company_rating, job.company_type = r.fit_score, r.company_rating, r.company_type
            job.work_mode = job.work_mode or r.work_mode
            changes = {
                "fit_score": r.fit_score, "company_rating": r.company_rating, "company_type": r.company_type,
                "work_mode": job.work_mode, "score_reason": r.reason,
                "matched_skills": ", ".join(r.matched_skills), "missing_skills": ", ".join(r.missing_skills),
                "status": Status.SHORTLISTED if passes_filters(job, cfg) else Status.NOT_A_FIT,
            }
            store.update_job(job.id, **changes)
            for k, v in changes.items():
                setattr(job, k, v)
            rated.append(job)
    return rated


def reapply_filters(settings, store) -> int:
    """Re-shortlist already-rated jobs after changing rating filters in Settings (no AI calls)."""
    cfg = settings.section("rating")
    changed = 0
    for job in store.list_jobs([Status.SHORTLISTED, Status.NOT_A_FIT]):
        if job.fit_score is None:
            continue
        new = Status.SHORTLISTED if passes_filters(job, cfg) else Status.NOT_A_FIT
        if new != job.status:
            store.update_job(job.id, status=new)
            changed += 1
    return changed
