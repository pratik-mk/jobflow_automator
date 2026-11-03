import logging

from core.models import Job
from core.store.base import JobStore

log = logging.getLogger(__name__)


class CompositeStore(JobStore):
    """Reads from the primary store; writes go to the primary and are mirrored best-effort."""

    name = "composite"

    def __init__(self, primary: JobStore, mirrors: list[JobStore]):
        self.primary = primary
        self.mirrors = mirrors

    def _mirror(self, method: str, *args, **kwargs) -> None:
        for m in self.mirrors:
            try:
                getattr(m, method)(*args, **kwargs)
            except Exception as e:
                log.warning("Mirror %s.%s failed: %s", m.name, method, e)

    def upsert_jobs(self, jobs: list[Job]) -> None:
        if jobs:
            self.primary.upsert_jobs(jobs)
            self._mirror("upsert_jobs", jobs)

    def replace_all(self, jobs: list[Job]) -> None:
        self.primary.replace_all(jobs)
        self._mirror("replace_all", jobs)

    def list_jobs(self, statuses=None) -> list[Job]:
        return self.primary.list_jobs(statuses)

    def get_job(self, job_id: str) -> Job | None:
        return self.primary.get_job(job_id)

    def update_job(self, job_id: str, **changes) -> None:
        self.primary.update_job(job_id, **changes)
        self._mirror("update_job", job_id, **changes)

    def existing_ids(self) -> set[str]:
        return self.primary.existing_ids()

    def sync_mirrors(self) -> int:
        """Copy every job from the primary into each mirror (e.g. after editing the Google Sheet by hand)."""
        jobs = self.primary.list_jobs()
        self._mirror("replace_all", jobs)
        return len(jobs)
