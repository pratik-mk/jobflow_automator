from abc import ABC, abstractmethod

from core.models import Job


class JobStore(ABC):
    """Storage backend contract. Add a backend by subclassing and registering it in core.store.get_store."""

    name = "base"

    @abstractmethod
    def upsert_jobs(self, jobs: list[Job]) -> None: ...

    @abstractmethod
    def replace_all(self, jobs: list[Job]) -> None: ...

    @abstractmethod
    def list_jobs(self, statuses: list[str] | None = None) -> list[Job]: ...

    @abstractmethod
    def get_job(self, job_id: str) -> Job | None: ...

    @abstractmethod
    def update_job(self, job_id: str, **changes) -> None: ...

    @abstractmethod
    def existing_ids(self) -> set[str]: ...
