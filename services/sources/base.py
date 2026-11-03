from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RawJob:
    """Source-agnostic job posting. Every source maps its results into this shape."""

    company: str
    title: str
    url: str
    description: str
    source: str
    location: str = ""
    work_mode: str = ""
    job_type: str = ""
    date_posted: str = ""
    salary: str = ""
    company_info: str = ""
    origin: str = ""


class JobSource(ABC):
    """A pluggable job source. Subclass, set `name`, decorate with @register_source, enable it in settings.json.

    `config` is this source's block from settings.json; `search` is the shared "search" block
    (e.g. posted_within_hours) that every source should respect.
    """

    name = "base"

    def __init__(self, config: dict, search: dict):
        self.config = config
        self.search = search

    @abstractmethod
    def fetch(self) -> list[RawJob]: ...
