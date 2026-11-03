import sqlite3
from pathlib import Path

from core.models import Job, now_iso
from core.store.base import JobStore

COLUMNS = Job.columns()


class SQLiteStore(JobStore):
    name = "sqlite"

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        cols = ", ".join("id TEXT PRIMARY KEY" if c == "id" else f"{c} TEXT" for c in COLUMNS)
        self.conn.execute(f"CREATE TABLE IF NOT EXISTS jobs ({cols})")
        existing = {r["name"] for r in self.conn.execute("PRAGMA table_info(jobs)")}
        for c in COLUMNS:
            if c not in existing:
                self.conn.execute(f"ALTER TABLE jobs ADD COLUMN {c} TEXT")
        self.conn.commit()

    def upsert_jobs(self, jobs: list[Job]) -> None:
        placeholders = ", ".join("?" for _ in COLUMNS)
        updates = ", ".join(f"{c}=excluded.{c}" for c in COLUMNS if c != "id")
        self.conn.executemany(
            f"INSERT INTO jobs ({', '.join(COLUMNS)}) VALUES ({placeholders}) ON CONFLICT(id) DO UPDATE SET {updates}",
            [[_s(j.to_dict()[c]) for c in COLUMNS] for j in jobs],
        )
        self.conn.commit()

    def replace_all(self, jobs: list[Job]) -> None:
        self.conn.execute("DELETE FROM jobs")
        self.upsert_jobs(jobs)

    def list_jobs(self, statuses: list[str] | None = None) -> list[Job]:
        if statuses:
            q = f"SELECT * FROM jobs WHERE status IN ({', '.join('?' for _ in statuses)}) ORDER BY date_scraped DESC"
            rows = self.conn.execute(q, statuses)
        else:
            rows = self.conn.execute("SELECT * FROM jobs ORDER BY date_scraped DESC")
        return [Job.from_dict(dict(r)) for r in rows]

    def get_job(self, job_id: str) -> Job | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return Job.from_dict(dict(row)) if row else None

    def update_job(self, job_id: str, **changes) -> None:
        changes = {k: v for k, v in changes.items() if k in COLUMNS}
        changes["updated_at"] = changes.get("updated_at") or now_iso()
        sets = ", ".join(f"{k} = ?" for k in changes)
        self.conn.execute(f"UPDATE jobs SET {sets} WHERE id = ?", [*map(_s, changes.values()), job_id])
        self.conn.commit()

    def existing_ids(self) -> set[str]:
        return {r[0] for r in self.conn.execute("SELECT id FROM jobs")}


def _s(value) -> str:
    return "" if value is None else str(value)
