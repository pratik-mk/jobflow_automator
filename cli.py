import argparse
import logging
import sqlite3
import sys

from core.config import load_settings
from core.models import Job, Status
from core.store import get_store
from services import resume_builder, scorer, scraper


def setup_logging(settings) -> None:
    settings.logs_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(settings.logs_dir / "run.log")],
    )
    for noisy in ("httpx", "urllib3", "JobSpy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def migrate(settings, store) -> int:
    """Move jobs saved by older versions into the current column layout (Sheets + SQLite)."""
    conn = sqlite3.connect(str(settings.sqlite_path))
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM jobs")]
    conn.close()
    jobs = []
    for r in rows:
        r["source"] = r.get("source") or r.get("site", "")
        if not r.get("company_rating") and r.get("company_score"):
            r["company_rating"] = r["company_score"]
        if r.get("status") == "rejected":
            r["status"] = Status.NOT_A_FIT
        jobs.append(Job.from_dict(r))
    store.replace_all(jobs)
    return len(jobs)


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="JobFlow Automator")
    parser.add_argument("command", choices=["search", "scrape", "rate", "build", "cover", "refilter", "sync", "migrate"],
                        help="search = scrape + rate | build = tailored resumes for shortlisted jobs | "
                             "cover = cover letter for --ids | refilter = re-apply rating filters | "
                             "sync = copy Sheet to SQLite | migrate = upgrade storage")
    parser.add_argument("--ids", nargs="*", help="Limit rate/build/cover to specific job ids")
    parser.add_argument("--notes", default="", help="Extra context for the cover letter (hiring manager, tone...)")
    args = parser.parse_args(argv)

    settings = load_settings()
    setup_logging(settings)
    log = logging.getLogger("cli")
    store = get_store(settings)

    if args.command in ("search", "scrape"):
        jobs, stats = scraper.scrape(settings, store)
        log.info("Scrape: %s", stats)
    if args.command in ("search", "rate"):
        rated = scorer.rate(settings, store, args.ids)
        log.info("Rated %d jobs, shortlisted %d", len(rated), sum(j.status == Status.SHORTLISTED for j in rated))
    if args.command == "build":
        built = resume_builder.build(settings, store, args.ids)
        log.info("Built %d resumes", len(built))
    if args.command == "cover":
        from services import cover_letter
        ids = args.ids or []
        for n, jid in enumerate(ids, 1):
            log.info("[%d/%d] cover letter...", n, len(ids))
            try:
                cover_letter.build(settings, store, jid, args.notes)
            except Exception as e:
                log.error("[%d/%d] cover letter FAILED: %s", n, len(ids), e)
        log.info("Done: %d cover letter(s)", len(ids))
    if args.command == "refilter":
        log.info("Re-filtered: %d jobs changed status", scorer.reapply_filters(settings, store))
    if args.command == "sync":
        log.info("Copied %d jobs from the primary store to mirrors", store.sync_mirrors())
    if args.command == "migrate":
        log.info("Migrated %d jobs to the current layout", migrate(settings, store))


if __name__ == "__main__":
    main()
