import hashlib
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit


class Status:
    NEW = "new"
    SHORTLISTED = "shortlisted"
    NOT_A_FIT = "not_a_fit"
    RESUME_READY = "resume_ready"
    APPLIED = "applied"
    RECRUITER_CALL = "recruiter_call"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    NO_RESPONSE = "no_response"
    WITHDRAWN = "withdrawn"
    SKIPPED = "skipped"
    NOT_AVAILABLE = "not_available"

    ALL = [NEW, SHORTLISTED, NOT_A_FIT, RESUME_READY, APPLIED, RECRUITER_CALL, INTERVIEWING,
           OFFER, REJECTED, NO_RESPONSE, WITHDRAWN, SKIPPED]
    LABELS = {
        NEW: "New", SHORTLISTED: "Shortlisted", NOT_A_FIT: "Not a fit", RESUME_READY: "Resume ready",
        APPLIED: "Applied", RECRUITER_CALL: "Got a call", INTERVIEWING: "Interviewing", OFFER: "Offer",
        REJECTED: "Rejected", NO_RESPONSE: "No response", WITHDRAWN: "Withdrawn", SKIPPED: "Skipped",
    }
    PIPELINE = [APPLIED, RECRUITER_CALL, INTERVIEWING, OFFER]
    LEGACY = {"scraped": NEW, "rejected_fit": NOT_A_FIT, "interview": INTERVIEWING, "applying": RESUME_READY,
              "needs_human": RESUME_READY, "failed": RESUME_READY}


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"), "", ""))


def job_id_for(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode()).hexdigest()[:12]


@dataclass
class Job:
    id: str
    company: str
    title: str
    url: str
    source: str = ""
    location: str = ""
    work_mode: str = ""
    job_type: str = ""
    salary: str = ""
    date_posted: str = ""
    date_scraped: str = ""
    status: str = Status.NEW
    fit_score: int | None = None
    company_rating: int | None = None
    company_type: str = ""
    score_reason: str = ""
    matched_skills: str = ""
    missing_skills: str = ""
    resume_path: str = ""
    ats_match: int | None = None
    resume_keywords: str = ""
    date_applied: str = ""
    notes: str = ""
    updated_at: str = ""
    company_info: str = ""
    description: str = ""
    cover_letter_path: str = ""

    INT_FIELDS = ("fit_score", "company_rating", "ats_match")

    @classmethod
    def columns(cls) -> list[str]:
        return [f.name for f in fields(cls)]

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        clean = {}
        for f in fields(cls):
            value = data.get(f.name, "")
            if f.name in cls.INT_FIELDS:
                try:
                    value = int(float(value)) if value not in ("", None) else None
                except ValueError:
                    value = None
            elif value is None:
                value = ""
            clean[f.name] = value
        clean["status"] = Status.LEGACY.get(clean["status"], clean["status"]) or Status.NEW
        return cls(**clean)

    def to_dict(self) -> dict:
        return asdict(self)
