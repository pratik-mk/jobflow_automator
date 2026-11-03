import logging
from collections import Counter

from core.models import Job, job_id_for, now_iso
from services.sources import RawJob, load_sources

log = logging.getLogger(__name__)


def _title_ok(title: str, filters: dict) -> bool:
    t = f" {title.lower()} "
    if any(k.lower() in t for k in filters.get("exclude_title_keywords", [])):
        return False
    include = filters.get("include_title_keywords", [])
    return not include or any(k.lower() in t for k in include)


def collect(settings) -> list[RawJob]:
    registry = load_sources()
    raw: list[RawJob] = []
    for name, cfg in settings.section("sources").items():
        if not cfg.get("enabled", False):
            continue
        cls = registry.get(name)
        if not cls:
            log.warning("Unknown source '%s' in settings (available: %s)", name, ", ".join(registry))
            continue
        try:
            log.info("Searching source: %s", name)
            jobs = cls(cfg, settings.section("search")).fetch()
            for j in jobs:
                j.origin = name
            log.info("Source %s returned %d jobs", name, len(jobs))
            raw.extend(jobs)
        except Exception:
            log.exception("Source %s failed", name)
    return raw


def scrape(settings, store) -> tuple[list[Job], dict]:
    filters = settings.section("filters")
    existing = store.existing_ids()
    per_company: Counter = Counter()
    scraped_at = now_iso()
    jobs: list[Job] = []
    stats: Counter = Counter()

    sources = settings.section("sources")
    for r in collect(settings):
        stats["found"] += 1
        cap = sources.get(r.origin, {}).get("max_per_company", filters.get("max_per_company", 99))
        jid = job_id_for(r.url)
        if jid in existing:
            stats["already_seen"] += 1
        elif not _title_ok(r.title, filters):
            stats["title_filtered"] += 1
        elif len(r.description) < filters.get("min_description_chars", 0):
            stats["short_description"] += 1
        elif per_company[r.company.lower()] >= cap:
            stats["company_cap"] += 1
        else:
            existing.add(jid)
            per_company[r.company.lower()] += 1
            jobs.append(Job(
                id=jid, company=r.company, title=r.title, url=r.url, source=r.source, location=r.location,
                work_mode=r.work_mode, job_type=r.job_type, salary=r.salary, date_posted=r.date_posted,
                date_scraped=scraped_at, company_info=r.company_info, description=r.description, updated_at=scraped_at,
            ))

    store.upsert_jobs(jobs)
    stats["new"] = len(jobs)
    log.info("Scrape stats: %s", dict(stats))
    return jobs, dict(stats)
