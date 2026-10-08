import ipaddress
import json
import logging
import re
import urllib.request

from fastapi import APIRouter, BackgroundTasks, Request
from pydantic import BaseModel, Field
from typing import Optional

from auth import client_ip
from database import SessionLocal
import db_models

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["analytics"])

BOT_PATTERN = re.compile(r"bot|crawl|spider|slurp|headless|preview|lighthouse|monitor|curl|wget|python-requests", re.I)


class TrackRequest(BaseModel):
    path: str = Field(..., min_length=1, max_length=500)
    referrer: Optional[str] = Field(None, max_length=1000)


def parse_user_agent(ua: str) -> tuple[str, str, str]:
    """Return (os, device_type, browser) from a User-Agent string."""
    s = ua.lower()

    if "android" in s:
        os_name = "Android"
    elif "iphone" in s or "ipad" in s:
        os_name = "iOS"
    elif "windows" in s:
        os_name = "Windows"
    elif "mac os x" in s:
        os_name = "macOS"
    elif "linux" in s:
        os_name = "Linux"
    else:
        os_name = "Unknown"

    if "ipad" in s or "tablet" in s:
        device = "tablet"
    elif "mobile" in s or "android" in s or "iphone" in s:
        device = "mobile"
    else:
        device = "desktop"

    if "edg/" in s:
        browser = "Edge"
    elif "opr/" in s or "opera" in s:
        browser = "Opera"
    elif "chrome/" in s or "crios/" in s:
        browser = "Chrome"
    elif "firefox/" in s or "fxios/" in s:
        browser = "Firefox"
    elif "safari/" in s:
        browser = "Safari"
    else:
        browser = "Unknown"

    return os_name, device, browser


def _is_public_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


def _lookup_geo(ip: str) -> dict:
    # ip-api.com free tier: no key, 45 req/min, http only
    if not _is_public_ip(ip):
        return {}
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,country,city,lat,lon"
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = json.load(resp)
        if data.get("status") == "success":
            return {
                "country": data.get("country"),
                "city": data.get("city"),
                "latitude": data.get("lat"),
                "longitude": data.get("lon"),
            }
    except Exception:
        logger.warning("Geo lookup failed for %s", ip)
    return {}


def record_visit(ip: str, user_agent: str, path: str, referrer: Optional[str]) -> None:
    os_name, device, browser = parse_user_agent(user_agent)
    geo = _lookup_geo(ip)
    db = SessionLocal()
    try:
        db.add(
            db_models.PageVisit(
                visitor_ip=ip,
                user_agent=user_agent[:1000],
                os=os_name,
                device_type=device,
                browser=browser,
                path=path,
                referrer=referrer or None,
                **geo,
            )
        )
        db.commit()
    except Exception:
        logger.exception("Failed to record visit")
        db.rollback()
    finally:
        db.close()


@router.post("/track", status_code=204)
async def track(payload: TrackRequest, request: Request, background_tasks: BackgroundTasks):
    user_agent = request.headers.get("user-agent", "")
    if not user_agent or BOT_PATTERN.search(user_agent) or payload.path.startswith("/admin"):
        return
    # Ignore referrers from our own site so "direct" vs external sources stay meaningful
    referrer = payload.referrer
    if referrer and re.match(r"^https?://([a-z0-9-]+\.)*cloudmindra\.com(/|$)", referrer, re.I):
        referrer = None
    background_tasks.add_task(record_visit, client_ip(request), user_agent, payload.path, referrer)
