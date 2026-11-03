"""Jobs straight from company career boards (Greenhouse, Lever, Ashby, Workday) via their public JSON feeds."""
import html
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import requests

from services.sources import register_source
from services.sources.base import JobSource, RawJob

log = logging.getLogger(__name__)
HEADERS = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 JobFlow"}
TIMEOUT = 25


def _text(raw: str) -> str:
    raw = html.unescape(raw or "")
    raw = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", raw, flags=re.I)
    raw = re.sub(r"<li[^>]*>", "- ", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", raw)).strip()


def _date(value) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc)
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _workday_date(posted_on: str) -> datetime | None:
    s = (posted_on or "").lower()
    now = datetime.now(timezone.utc)
    if "today" in s:
        return now
    if "yesterday" in s:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*day", s)
    return now - timedelta(days=int(m.group(1))) if m else None


class _Board:
    def __init__(self, cfg: dict, search: dict):
        self.locations = [k.lower() for k in cfg.get("locations", ["india", "bangalore", "bengaluru"])]
        days = cfg.get("max_age_days") or max(1, search.get("posted_within_hours", 168) // 24)
        self.cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    def location_ok(self, location: str) -> bool:
        loc = (location or "").lower()
        return not self.locations or any(k in loc for k in self.locations)

    def fresh(self, when: datetime | None) -> bool:
        return when is None or when.astimezone(timezone.utc) >= self.cutoff

    @staticmethod
    def raw(company, title, url, description, source, location, when, work_mode="", job_type=""):
        return RawJob(company=company, title=title, url=url, description=description, source=source,
                      location=location, work_mode=work_mode, job_type=job_type,
                      date_posted=when.strftime("%Y-%m-%d") if when else "")


def _greenhouse(b: _Board, token: str, name: str) -> list[RawJob]:
    data = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true",
                        headers=HEADERS, timeout=TIMEOUT).json()
    out = []
    for j in data.get("jobs", []):
        loc = (j.get("location") or {}).get("name", "")
        when = _date(j.get("first_published") or j.get("updated_at"))
        if b.location_ok(loc) and b.fresh(when):
            out.append(b.raw(name or j.get("company_name") or token, j["title"], j["absolute_url"],
                             _text(j.get("content", "")), "greenhouse", loc, when))
    return out


def _lever(b: _Board, token: str, name: str) -> list[RawJob]:
    data = requests.get(f"https://api.lever.co/v0/postings/{token}?mode=json", headers=HEADERS, timeout=TIMEOUT).json()
    out = []
    for j in data:
        cat = j.get("categories") or {}
        loc = ", ".join(cat.get("allLocations") or [cat.get("location", "")])
        when = _date(j.get("createdAt"))
        if b.location_ok(loc) and b.fresh(when):
            lists = "\n".join(f"{x.get('text', '')}\n{_text(x.get('content', ''))}" for x in j.get("lists", []))
            desc = "\n\n".join(filter(None, [j.get("descriptionPlain", ""), lists, j.get("additionalPlain", "")]))
            out.append(b.raw(name or token.title(), j["text"], j["hostedUrl"], desc, "lever", loc, when,
                             work_mode=j.get("workplaceType", ""), job_type=cat.get("commitment", "")))
    return out


def _ashby(b: _Board, token: str, name: str) -> list[RawJob]:
    data = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{token}", headers=HEADERS, timeout=TIMEOUT).json()
    out = []
    for j in data.get("jobs", []):
        if not j.get("isListed", True):
            continue
        locs = [j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations") or []]
        loc = ", ".join(filter(None, locs))
        when = _date(j.get("publishedAt"))
        if b.location_ok(loc) and b.fresh(when):
            out.append(b.raw(name or token.title(), j["title"], j["jobUrl"], j.get("descriptionPlain") or "", "ashby",
                             loc, when, work_mode=(j.get("workplaceType") or "").lower(), job_type=j.get("employmentType", "")))
    return out


def _workday(b: _Board, url: str, name: str, terms: list[str]) -> list[RawJob]:
    parts = urlsplit(url)
    tenant, site = parts.netloc.split(".")[0], parts.path.strip("/").split("/")[-1]
    api = f"https://{parts.netloc}/wday/cxs/{tenant}/{site}"
    seen, picked = set(), []
    for term in terms:
        for offset in (0, 20):
            r = requests.post(f"{api}/jobs", json={"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term},
                              headers=HEADERS, timeout=TIMEOUT)
            if r.status_code != 200:
                log.warning("Workday %s returned %s", name, r.status_code)
                break
            posts = r.json().get("jobPostings", [])
            for p in posts:
                when = _workday_date(p.get("postedOn", ""))
                if p["externalPath"] not in seen and b.location_ok(p.get("locationsText", "")) and b.fresh(when):
                    seen.add(p["externalPath"])
                    picked.append((p, when))
            if len(posts) < 20:
                break
    out = []
    for p, when in picked:
        try:
            d = requests.get(f"{api}{p['externalPath']}", headers=HEADERS, timeout=TIMEOUT).json()["jobPostingInfo"]
        except Exception as e:
            log.warning("Workday detail failed for %s: %s", p.get("title"), e)
            continue
        out.append(b.raw(name, d.get("title", p["title"]), d.get("externalUrl") or f"{url}{p['externalPath']}",
                         _text(d.get("jobDescription", "")), "workday", d.get("location") or p.get("locationsText", ""),
                         _date(d.get("startDate")) or when, job_type=d.get("timeType", "")))
    return out


@register_source
class CompanyBoardsSource(JobSource):
    """Career boards of selected companies. Configure company lists per platform in settings.json."""

    name = "company_boards"

    def fetch(self) -> list[RawJob]:
        cfg, board = self.config, _Board(self.config, self.search)
        terms = cfg.get("workday_search_terms", ["software engineer", "full stack", "developer"])
        tasks = ([(_greenhouse, t, n) for t, n in cfg.get("greenhouse", {}).items()]
                 + [(_lever, t, n) for t, n in cfg.get("lever", {}).items()]
                 + [(_ashby, t, n) for t, n in cfg.get("ashby", {}).items()]
                 + [(lambda b, u, n: _workday(b, u, n, terms), w["url"], w["company"]) for w in cfg.get("workday", [])])

        def run(task):
            fn, key, name = task
            try:
                jobs = fn(board, key, name)
                log.info("  %s: %d matching jobs", name or key, len(jobs))
                return jobs
            except Exception as e:
                log.warning("  %s failed: %s", name or key, e)
                return []

        with ThreadPoolExecutor(max_workers=8) as pool:
            return [job for jobs in pool.map(run, tasks) for job in jobs]
