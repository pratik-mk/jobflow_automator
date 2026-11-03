import logging

import gspread
from google.oauth2.service_account import Credentials
from gspread.utils import rowcol_to_a1

from core.models import Job, now_iso
from core.store.base import JobStore

log = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
JOBS_TAB = "Jobs"
COLUMNS = Job.columns()
CELL_LIMIT = 49000


class SheetsStore(JobStore):
    name = "sheets"

    def __init__(self, credentials_file, sheet_url: str):
        creds = Credentials.from_service_account_file(str(credentials_file), scopes=SCOPES)
        self.book = gspread.authorize(creds).open_by_url(sheet_url)
        try:
            self.ws = self.book.worksheet(JOBS_TAB)
        except gspread.WorksheetNotFound:
            self.ws = self.book.add_worksheet(title=JOBS_TAB, rows=1000, cols=len(COLUMNS))
        if self.ws.col_count < len(COLUMNS):
            self.ws.resize(cols=len(COLUMNS))
        header = self.ws.row_values(1)
        if header != COLUMNS and header == COLUMNS[:len(header)]:
            self.ws.update(range_name="A1", values=[COLUMNS], value_input_option="RAW")
        self._row_index: dict[str, int] | None = None

    def headers_match(self) -> bool:
        return self.ws.row_values(1) == COLUMNS

    def _index(self) -> dict[str, int]:
        if self._row_index is None:
            ids = self.ws.col_values(1)
            self._row_index = {v: i for i, v in enumerate(ids, start=1) if i > 1 and v}
        return self._row_index

    @staticmethod
    def _row(job: Job) -> list:
        d = job.to_dict()
        return [("" if d[c] is None else str(d[c]))[:CELL_LIMIT] for c in COLUMNS]

    def replace_all(self, jobs: list[Job]) -> None:
        """Rewrite the whole tab in the current column layout (used for schema migrations)."""
        self.ws.clear()
        self.ws.resize(rows=max(len(jobs) + 50, 200), cols=len(COLUMNS))
        self.ws.update(range_name="A1", values=[COLUMNS] + [self._row(j) for j in jobs], value_input_option="RAW")
        self.ws.freeze(rows=1)
        self._row_index = None

    def upsert_jobs(self, jobs: list[Job]) -> None:
        if not self.headers_match():
            raise RuntimeError("Jobs sheet columns are out of date - run: python cli.py migrate")
        index = self._index()
        new_rows, updates = [], []
        for job in jobs:
            if job.id in index:
                r = index[job.id]
                updates.append({"range": f"A{r}:{rowcol_to_a1(r, len(COLUMNS))}", "values": [self._row(job)]})
            else:
                new_rows.append(self._row(job))
        if updates:
            self.ws.batch_update(updates, value_input_option="RAW")
        if new_rows:
            self.ws.append_rows(new_rows, value_input_option="RAW")
            self._row_index = None

    def list_jobs(self, statuses: list[str] | None = None) -> list[Job]:
        values = self.ws.get_all_values()
        if not values:
            return []
        header = values[0]
        jobs = [Job.from_dict(dict(zip(header, row))) for row in values[1:] if row and row[0]]
        return [j for j in jobs if not statuses or j.status in statuses]

    def get_job(self, job_id: str) -> Job | None:
        r = self._index().get(job_id)
        if not r:
            return None
        row = self.ws.row_values(r)
        return Job.from_dict(dict(zip(COLUMNS, row + [""] * (len(COLUMNS) - len(row)))))

    def update_job(self, job_id: str, **changes) -> None:
        r = self._index().get(job_id)
        if not r:
            log.warning("Sheets: job %s not found", job_id)
            return
        changes["updated_at"] = changes.get("updated_at") or now_iso()
        cells = [{"range": rowcol_to_a1(r, COLUMNS.index(k) + 1), "values": [["" if v is None else str(v)[:CELL_LIMIT]]]}
                 for k, v in changes.items() if k in COLUMNS]
        self.ws.batch_update(cells, value_input_option="RAW")

    def existing_ids(self) -> set[str]:
        return set(self._index())
