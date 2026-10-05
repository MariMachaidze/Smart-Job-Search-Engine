"""
orchestrator/scheduler_service.py -- long-running scheduler process
(workstream K, plan section 9).

Wires the three daily batch jobs from `orchestrator.scheduled_jobs` into an
APScheduler `AsyncIOScheduler` with cron triggers:
  - hour=5: qualifications update  (before discovery, so scoring uses the fresh prompt)
  - hour=6: discovery               (time TBD/configurable per the plan)
  - hour=8: digest                  (after discovery+scoring settle)

APScheduler (AsyncIOScheduler), not raw cron, so the scheduler stays
in-process with the rest of the Python codebase and needs no separate infra
-- per the plan's explicit rationale in section 9.

Run as its own long-lived process/container (see docker-compose.yml's
`scheduler` service), started with:

    python -m orchestrator.scheduler_service

This mirrors the existing `scraper`/`app` services' "Dockerfile installs
requirements.txt, then runs the code" pattern, but -- unlike the `scraper`
service, which idles with `CMD ["tail", "-f", "/dev/null"]` because it's only
ever invoked as a library by other code -- this service's whole job *is* to
run continuously, so `main()` actually starts the scheduler and blocks
forever on a live asyncio event loop (AsyncIOScheduler needs one to fire
cron jobs at the right wall-clock time).
"""
import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from orchestrator.scheduled_jobs import (
    run_daily_digest_for_all_users,
    run_daily_discovery_for_all_users,
    run_daily_qualifications_update_for_all_users,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def build_scheduler() -> AsyncIOScheduler:
    """Builds (but does not start) an AsyncIOScheduler with all three daily
    jobs registered. Factored out from main()/__main__ so tests/other code
    can inspect `scheduler.get_jobs()` (ids, cron fields, next run time)
    without starting a real event loop or waiting for anything to fire."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_daily_qualifications_update_for_all_users,
        "cron",
        hour=5,
        id="daily_qualifications_update",
        name="Daily qualifications prompt update (all users)",
    )
    scheduler.add_job(
        run_daily_discovery_for_all_users,
        "cron",
        hour=6,
        id="daily_discovery",
        name="Daily job discovery (all users)",
    )
    scheduler.add_job(
        run_daily_digest_for_all_users,
        "cron",
        hour=8,
        id="daily_digest",
        name="Daily relevant-but-unapplied digest (all users)",
    )
    return scheduler


async def _serve_forever(scheduler: AsyncIOScheduler) -> None:
    scheduler.start()
    logger.info(
        "Scheduler started with jobs: %s",
        [(job.id, str(job.trigger)) for job in scheduler.get_jobs()],
    )
    try:
        # Block forever; AsyncIOScheduler fires jobs on this same running
        # event loop at their cron-scheduled times. Interrupted by
        # KeyboardInterrupt/SIGTERM, which cancels this await and falls
        # through to the shutdown below.
        await asyncio.Event().wait()
    finally:
        scheduler.shutdown(wait=False)


def main() -> None:
    scheduler = build_scheduler()
    try:
        asyncio.run(_serve_forever(scheduler))
    except KeyboardInterrupt:
        logger.info("Scheduler service interrupted, shutting down.")


if __name__ == "__main__":
    main()
