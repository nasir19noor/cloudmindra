"""Uptime monitoring: HTTP checks, SSL expiry, up/down state, and the check loop run by the worker.

State changes are written as events to uptime.outbox in the same transaction; the alert
emails are sent by event handlers (apps/uptime/handlers.py) through the job queue."""
import asyncio
import ipaddress
import logging
import os
import socket
import ssl
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import httpx

from core.database import SessionLocal
from core.entitlements import limits as module_limits
from core.outbox import emit
from apps.uptime import models as db_models

logger = logging.getLogger(__name__)

INTERVALS = (1, 5, 15, 30, 60)  # minutes; the tier's uptime.min_interval decides which are allowed
REQUEST_TIMEOUT = 10  # seconds
FAILURES_BEFORE_DOWN = 2  # one blip should not page anyone
SSL_CHECK_EVERY = timedelta(hours=6)
SSL_WARN_DAYS = 14
WORKER_TICK = 30  # seconds between scheduler passes
MAX_CONCURRENT_CHECKS = 20
USER_AGENT = "CloudMindra-Uptime/1.0 (+https://cloudmindra.com)"


def allowed_intervals(min_interval: int) -> list[int]:
    return [i for i in INTERVALS if i >= min_interval]


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def aware(dt: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes; Postgres keeps the timezone
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# --- URL safety -----------------------------------------------------------

class UnsafeURL(ValueError):
    pass


def normalize_url(raw: str) -> str:
    """Validate a customer URL's shape. Raises UnsafeURL with a readable message."""
    url = raw.strip()
    if "://" not in url:
        url = f"https://{url}"
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise UnsafeURL("Only http:// and https:// URLs can be monitored")
    if not parts.hostname:
        raise UnsafeURL("Enter a full URL, for example https://example.com")
    if parts.username or parts.password:
        raise UnsafeURL("URLs with a username or password are not supported")
    if len(url) > 2048:
        raise UnsafeURL("URL is too long")
    return url


def assert_public_host(url: str) -> None:
    """Refuse hosts that resolve to private, loopback or link-local addresses.

    The backend shares the host network with PostgreSQL and other services, so
    customer URLs must never reach anything that is not on the public internet.
    """
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(parts.hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeURL(f"Could not resolve {parts.hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise UnsafeURL("This address is not on the public internet")


# --- Checks ---------------------------------------------------------------

async def http_check(url: str) -> dict:
    """One request. Any response below 400 counts as up; redirects are not followed."""
    started = time.perf_counter()
    try:
        await asyncio.to_thread(assert_public_host, url)
        async with httpx.AsyncClient(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(url)
        ms = int((time.perf_counter() - started) * 1000)
        ok = resp.status_code < 400
        return {"ok": ok, "status_code": resp.status_code, "response_ms": ms,
                "error": None if ok else f"HTTP {resp.status_code}"}
    except UnsafeURL as exc:
        return {"ok": False, "status_code": None, "response_ms": None, "error": str(exc)}
    except httpx.TimeoutException:
        return {"ok": False, "status_code": None, "response_ms": None, "error": f"Timed out after {REQUEST_TIMEOUT}s"}
    except httpx.ConnectError as exc:
        reason = "SSL certificate problem" if "certificate" in str(exc).lower() else "Connection failed"
        return {"ok": False, "status_code": None, "response_ms": None, "error": reason}
    except httpx.HTTPError as exc:
        return {"ok": False, "status_code": None, "response_ms": None, "error": type(exc).__name__}


def ssl_expiry(url: str) -> datetime | None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        return None
    try:
        assert_public_host(url)
        ctx = ssl.create_default_context()
        with socket.create_connection((parts.hostname, parts.port or 443), timeout=REQUEST_TIMEOUT) as sock:
            with ctx.wrap_socket(sock, server_hostname=parts.hostname) as tls:
                not_after = tls.getpeercert()["notAfter"]
        return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), tz=timezone.utc)
    except Exception:
        # An invalid certificate already fails the HTTP check with a clear error
        return None


# --- Recording and alerts -------------------------------------------------

def _fmt_duration(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 1)} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if hours < 24 else f"{hours // 24} d {hours % 24} h"


def _portal_link(org_id: str) -> str:
    """The workspace's uptime page (DESIGN.md §11)."""
    return f"{os.getenv('FRONTEND_URL', 'https://cloudmindra.com').rstrip('/')}/portal/{org_id}/uptime"


def record_result(monitor_id: str, result: dict, ssl_expires: datetime | None, ssl_checked: bool) -> None:
    """Store one check, move the monitor between up/down, and record alert events."""
    alerts: list[tuple[str, str, str]] = []  # (event type, subject, body)
    db = SessionLocal()
    try:
        m = db.get(db_models.Monitor, monitor_id)
        if m is None:  # deleted while the check was running
            return
        now = utcnow()

        db.add(db_models.MonitorCheck(monitor_id=m.id, checked_at=now, ok=result["ok"],
                                      status_code=result["status_code"], response_ms=result["response_ms"],
                                      error=result["error"]))
        m.last_checked_at = now
        m.last_status_code = result["status_code"]
        m.last_response_ms = result["response_ms"]
        m.last_error = result["error"]

        if result["ok"]:
            if m.status == "down":
                downtime = _fmt_duration(now - aware(m.down_since)) if m.down_since else "a while"
                alerts.append(("uptime.recovered", f"✅ {m.name} is back up",
                               f"{m.name} ({m.url}) is responding again after {downtime} of downtime.\n\n"
                               f"Status: HTTP {result['status_code']} in {result['response_ms']} ms\n\n{_portal_link(m.org_id)}\n"))
            m.status = "up"
            m.consecutive_failures = 0
            m.down_since = None
        else:
            m.consecutive_failures += 1
            if m.consecutive_failures >= FAILURES_BEFORE_DOWN and m.status != "down":
                m.status = "down"
                m.down_since = now
                alerts.append(("uptime.down", f"🔴 {m.name} is down",
                               f"{m.name} ({m.url}) failed {m.consecutive_failures} checks in a row.\n\n"
                               f"Error: {result['error']}\n"
                               f"Detected: {now:%Y-%m-%d %H:%M} UTC\n\n"
                               f"We'll email you again when it recovers.\n\n{_portal_link(m.org_id)}\n"))

        if ssl_checked:
            m.ssl_checked_at = now
            m.ssl_expires_at = ssl_expires
            if ssl_expires:
                days_left = (ssl_expires - now).days
                already_warned = aware(m.ssl_alerted_for) == ssl_expires
                if days_left <= SSL_WARN_DAYS and not already_warned:
                    m.ssl_alerted_for = ssl_expires
                    alerts.append(("uptime.ssl_expiring", f"⚠️ SSL certificate for {m.name} expires in {max(days_left, 0)} days",
                                   f"The SSL certificate for {m.url} expires on {ssl_expires:%Y-%m-%d}.\n\n"
                                   f"Renew it before then to avoid browser security warnings.\n\n{_portal_link(m.org_id)}\n"))
        # Same transaction as the state change: the alert exists exactly when the change does
        for event_type, subject, body in alerts:
            emit(db, db_models.UptimeOutbox, event_type, m.org_id,
                 {"monitor_id": m.id, "name": m.name, "url": m.url, "subject": subject, "body": body})
        db.commit()
    finally:
        db.close()


async def run_check(monitor_id: str, url: str, ssl_due: bool) -> None:
    result = await http_check(url)
    expires = await asyncio.to_thread(ssl_expiry, url) if ssl_due else None
    await asyncio.to_thread(record_result, monitor_id, result, expires, ssl_due)


def ssl_due(m: db_models.Monitor, now: datetime) -> bool:
    return m.url.startswith("https://") and (m.ssl_checked_at is None or now - aware(m.ssl_checked_at) >= SSL_CHECK_EVERY)


# --- Worker ---------------------------------------------------------------

def _due_monitors() -> list[tuple[str, str, bool]]:
    now = utcnow()
    db = SessionLocal()
    try:
        due = []
        min_interval: dict[str, int] = {}  # per workspace, looked up once per pass
        for m in db.query(db_models.Monitor).filter(db_models.Monitor.is_active.is_(True)).all():
            if m.org_id not in min_interval:
                min_interval[m.org_id] = module_limits(db, m.org_id, "uptime")["uptime.min_interval"]
            # A monitor saved at 1 minute on Pro is checked at the Free minimum after a downgrade
            interval = max(m.interval_minutes, min_interval[m.org_id])
            last = aware(m.last_checked_at)
            # Small slack so a check finishing a few seconds late is not skipped a whole tick
            if last is None or now - last >= timedelta(minutes=interval, seconds=-WORKER_TICK / 2):
                due.append((m.id, m.url, ssl_due(m, now)))
        return due
    finally:
        db.close()


def _prune_old_checks() -> None:
    """Keep each workspace's check history for its tier's uptime.history_days (7 Free / 90 Pro)."""
    db = SessionLocal()
    try:
        by_org: dict[str, list[str]] = {}
        for m_id, org_id in db.query(db_models.Monitor.id, db_models.Monitor.org_id):
            by_org.setdefault(org_id, []).append(m_id)
        now = utcnow()
        for org_id, ids in by_org.items():
            days = module_limits(db, org_id, "uptime")["uptime.history_days"]
            db.query(db_models.MonitorCheck).filter(
                db_models.MonitorCheck.monitor_id.in_(ids),
                db_models.MonitorCheck.checked_at < now - timedelta(days=days),
            ).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()


async def run_due_checks() -> int:
    due = await asyncio.to_thread(_due_monitors)
    sem = asyncio.Semaphore(MAX_CONCURRENT_CHECKS)

    async def guarded(args):
        async with sem:
            try:
                await run_check(*args)
            except Exception:
                logger.exception("Uptime check failed for monitor %s", args[0])

    await asyncio.gather(*(guarded(args) for args in due))
    return len(due)


UPTIME_LEADER_LOCK = 724101  # pg_advisory_lock key: one worker runs uptime checks at a time


async def worker() -> None:
    """Uptime check loop, run by the worker container (worker.py).

    Several workers may run (WORKER_APPS); only the one holding the advisory lock checks
    sites, the others stand by and take over if it stops, so a site is never checked twice.
    """
    from sqlalchemy import text
    from core.database import engine_for_schema

    logger.info("Uptime loop started; waiting to become leader")
    last_prune = 0.0
    while True:
        try:
            with engine_for_schema("uptime").connect() as conn:
                if not conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": UPTIME_LEADER_LOCK}).scalar():
                    await asyncio.sleep(WORKER_TICK)
                    continue
                logger.info("Uptime loop is leader")
                try:
                    while True:
                        await run_due_checks()
                        if time.monotonic() - last_prune > 3600:
                            await asyncio.to_thread(_prune_old_checks)
                            last_prune = time.monotonic()
                        await asyncio.sleep(WORKER_TICK)
                finally:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": UPTIME_LEADER_LOCK})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Uptime loop failed; retrying")
            await asyncio.sleep(WORKER_TICK)
