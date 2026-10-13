"""Background worker (DESIGN.md §2.2, §7). Runs in its own container:

    python migrate.py && python worker.py

- Platform loop: relay outbox events → jobs, run due jobs (retries, backoff), turn due
  schedules into jobs, and put back jobs stuck after a crash.
- Module loops: e.g. the uptime check loop. WORKER_APPS selects which modules this worker
  runs (comma-separated, default all), so one module can be scaled or moved on its own.
- Several workers are safe: jobs are claimed with SKIP LOCKED and the uptime loop elects
  one leader with an advisory lock.
"""
import asyncio
import logging
import os
import signal

from apps import MODULES
from core import jobs, outbox
from core.database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # one INFO line per uptime check is too noisy
log = logging.getLogger("worker")

POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "3"))
JOB_BATCH = int(os.getenv("WORKER_JOB_BATCH", "10"))
MAINTENANCE_EVERY = 60  # seconds between stuck-job checks


def platform_pass() -> int:
    """One pass of outbox relay + schedules + due jobs. Returns jobs run."""
    db = SessionLocal()
    try:
        outbox.relay(db)
        jobs.enqueue_due_schedules(db)
        claimed = jobs.claim(db, JOB_BATCH)
    finally:
        db.close()
    for job_id in claimed:
        session = SessionLocal()
        try:
            jobs.run_job(session, job_id)
        finally:
            session.close()
    return len(claimed)


async def platform_loop() -> None:
    log.info("Platform loop started (poll %ss)", POLL_SECONDS)
    since_maintenance = 0.0
    while True:
        try:
            ran = await asyncio.to_thread(platform_pass)
            since_maintenance += POLL_SECONDS
            if since_maintenance >= MAINTENANCE_EVERY:
                since_maintenance = 0
                db = SessionLocal()
                try:
                    if (n := jobs.requeue_stuck(db)):
                        log.warning("Requeued %s stuck jobs", n)
                finally:
                    db.close()
            if ran:
                continue  # more work may be waiting
        except Exception:
            log.exception("Platform pass failed")
        await asyncio.sleep(POLL_SECONDS)


def selected_modules() -> dict:
    wanted = os.getenv("WORKER_APPS", "").strip()
    if not wanted:
        return MODULES
    keys = {k.strip() for k in wanted.split(",") if k.strip()}
    unknown = keys - MODULES.keys()
    if unknown:
        raise SystemExit(f"WORKER_APPS has unknown modules: {', '.join(sorted(unknown))}")
    return {k: m for k, m in MODULES.items() if k in keys}


async def main() -> None:
    tasks = [asyncio.create_task(platform_loop(), name="platform")]
    for key, module in selected_modules().items():
        loop = getattr(module, "worker_loop", None)
        if loop:
            tasks.append(asyncio.create_task(loop(), name=key))
    log.info("Worker running: %s", ", ".join(t.get_name() for t in tasks))

    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows
            pass
    await stop.wait()
    log.info("Stopping worker")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
