"""Uptime monitoring: HTTP checks, SSL expiry, alert emails and the background worker."""
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

from database import SessionLocal
from mailer import send_alert_email
import db_models

logger = logging.getLogger(__name__)

INTERVALS = (1, 5, 15, 30, 60)  # minutes a customer can choose
REQUEST_TIMEOUT = 10  # seconds
FAILURES_BEFORE_DOWN = 2  # one blip should not page anyone
SSL_CHECK_EVERY = timedelta(hours=6)
SSL_WARN_DAYS = 14
CHECK_RETENTION = timedelta(days=30)
WORKER_TICK = 30  # seconds between scheduler passes
MAX_CONCURRENT_CHECKS = 20
USER_AGENT = "CloudMindra-Uptime/1.0 (+https://cloudmindra.com)"


def max_monitors_per_user() -> int:
    return int(os.getenv("MONITOR_LIMIT", "10"))


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


def _portal_link() -> str:
    return f"{os.getenv('FRONTEND_URL', 'https://cloudmindra.com').rstrip('/')}/portal"


def record_result(monitor_id: str, result: dict, ssl_expires: datetime | None, ssl_checked: bool) -> None:
    """Store one check, move the monitor between up/down, and email on changes."""
    alerts: list[tuple[str, str, str]] = []
    db = SessionLocal()
    try:
        m = db.get(db_models.Monitor, monitor_id)
        if m is None:  # deleted while the check was running
            return
        owner = db.get(db_models.User, m.user_id)
        now = utcnow()

        db.add(db_models.MonitorCheck(monitor_id=m.id, checked_at=now, ok=result["ok"],
                                      status_code=result["status_code"], response_ms=result["response_ms"],
                                      error=result["error"]))
        m.last_checked_at = now
        m.last_status_code = result["status_code"]
        m.last_response_ms = result["response_ms"]
        m.last_error = result["error"]

        if result["ok"]:
            if m.status == "down" and owner:
                downtime = _fmt_duration(now - aware(m.down_since)) if m.down_since else "a while"
                alerts.append((owner.email, f"✅ {m.name} is back up",
                               f"{m.name} ({m.url}) is responding again after {downtime} of downtime.\n\n"
                               f"Status: HTTP {result['status_code']} in {result['response_ms']} ms\n\n{_portal_link()}\n"))
            m.status = "up"
            m.consecutive_failures = 0
            m.down_since = None
        else:
            m.consecutive_failures += 1
            if m.consecutive_failures >= FAILURES_BEFORE_DOWN and m.status != "down":
                m.status = "down"
                m.down_since = now
                if owner:
                    alerts.append((owner.email, f"🔴 {m.name} is down",
                                   f"{m.name} ({m.url}) failed {m.consecutive_failures} checks in a row.\n\n"
                                   f"Error: {result['error']}\n"
                                   f"Detected: {now:%Y-%m-%d %H:%M} UTC\n\n"
                                   f"We'll email you again when it recovers.\n\n{_portal_link()}\n"))

        if ssl_checked:
            m.ssl_checked_at = now
            m.ssl_expires_at = ssl_expires
            if ssl_expires and owner:
                days_left = (ssl_expires - now).days
                already_warned = aware(m.ssl_alerted_for) == ssl_expires
                if days_left <= SSL_WARN_DAYS and not already_warned:
                    m.ssl_alerted_for = ssl_expires
                    alerts.append((owner.email, f"⚠️ SSL certificate for {m.name} expires in {max(days_left, 0)} days",
                                   f"The SSL certificate for {m.url} expires on {ssl_expires:%Y-%m-%d}.\n\n"
                                   f"Renew it before then to avoid browser security warnings.\n\n{_portal_link()}\n"))
        db.commit()
    finally:
        db.close()

    for to, subject, body in alerts:
        send_alert_email(to, subject, body)


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
        for m in db.query(db_models.Monitor).filter(db_models.Monitor.is_active.is_(True)).all():
            last = aware(m.last_checked_at)
            # Small slack so a check finishing a few seconds late is not skipped a whole tick
            if last is None or now - last >= timedelta(minutes=m.interval_minutes, seconds=-WORKER_TICK / 2):
                due.append((m.id, m.url, ssl_due(m, now)))
        return due
    finally:
        db.close()


def _prune_old_checks() -> None:
    db = SessionLocal()
    try:
        cutoff = utcnow() - CHECK_RETENTION
        db.query(db_models.MonitorCheck).filter(db_models.MonitorCheck.checked_at < cutoff).delete()
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


async def worker() -> None:
    """Runs inside the API process. Assumes a single uvicorn worker, as in the Dockerfile."""
    logger.info("Uptime monitor worker started")
    last_prune = 0.0
    while True:
        try:
            await run_due_checks()
            if time.monotonic() - last_prune > 3600:
                await asyncio.to_thread(_prune_old_checks)
                last_prune = time.monotonic()
        except Exception:
            logger.exception("Uptime monitor pass failed")
        await asyncio.sleep(WORKER_TICK)
