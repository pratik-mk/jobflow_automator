import logging

from jobspy import scrape_jobs

from services.sources import register_source
from services.sources.base import JobSource, RawJob

log = logging.getLogger(__name__)


def _clean(value) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return ""
    return str(value).strip()


def _salary(row: dict) -> str:
    lo, hi = _clean(row.get("min_amount")), _clean(row.get("max_amount"))
    if not lo and not hi:
        return ""
    return f"{lo}-{hi} {_clean(row.get('currency'))} {_clean(row.get('interval'))}".strip()


def _company_info(row: dict) -> str:
    parts = [("industry", row.get("company_industry")), ("employees", row.get("company_num_employees")),
             ("revenue", row.get("company_revenue")), ("rating", row.get("company_rating")),
             ("level", row.get("job_level"))]
    return "; ".join(f"{k}: {_clean(v)}" for k, v in parts if _clean(v))


@register_source
class JobSpySource(JobSource):
    """LinkedIn, Naukri, Indeed, Glassdoor and Google Jobs via python-jobspy."""

    name = "jobspy"

    def fetch(self) -> list[RawJob]:
        cfg = self.config
        out: list[RawJob] = []
        for term in cfg.get("terms", []):
            kwargs = dict(
                site_name=cfg.get("sites", ["linkedin"]), search_term=term, location=cfg.get("location", ""),
                hours_old=self.search.get("posted_within_hours", 24), results_wanted=cfg.get("results_wanted", 20),
                country_indeed=cfg.get("country_indeed", "India"), linkedin_fetch_description=True,
            )
            if cfg.get("job_type"):
                kwargs["job_type"] = cfg["job_type"]
            if cfg.get("remote_only"):
                kwargs["is_remote"] = True
            try:
                df = scrape_jobs(**kwargs)
            except Exception as e:
                log.error("JobSpy failed for '%s': %s", term, e)
                continue
            for row in df.to_dict(orient="records"):
                site = _clean(row.get("site"))
                if site == "linkedin":
                    url = _clean(row.get("job_url")) or _clean(row.get("job_url_direct"))
                else:
                    url = _clean(row.get("job_url_direct")) or _clean(row.get("job_url"))
                if not url:
                    continue
                remote = _clean(row.get("is_remote")).lower()
                out.append(RawJob(
                    company=_clean(row.get("company")), title=_clean(row.get("title")), url=url,
                    description=_clean(row.get("description")), source=site,
                    location=_clean(row.get("location")), work_mode="remote" if remote == "true" else "",
                    job_type=_clean(row.get("job_type")), date_posted=_clean(row.get("date_posted")),
                    salary=_salary(row), company_info=_company_info(row),
                ))
        return out
