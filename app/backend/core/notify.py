"""Notifications to workspace members (DESIGN.md §7).

notify() runs inside an event handler and fans out one "notify.email" job per recipient,
deduplicated per event and address. Each email is retried on its own, so a failure for one
member never re-sends the alert to everyone else. Members who switched the event off in
their alert settings (core.notification_prefs) are skipped.
"""
import os

from sqlalchemy.orm import Session

from core import jobs
from core.mailer import send_alert_email, smtp_configured
from core.orgs import alert_recipients


class DeliveryFailed(RuntimeError):
    """Raised so the job is retried."""


def settings_link(org_id: str) -> str:
    return f"{os.getenv('FRONTEND_URL', 'https://cloudmindra.com').rstrip('/')}/portal/{org_id}/alerts"


def notify(db: Session, org_id: str, event_key: str, subject: str, body: str, *, dedupe: str) -> int:
    """Queue the alert for every member who wants it. `dedupe` is the event id. Returns recipients queued."""
    recipients = alert_recipients(db, org_id, event_key)
    if not smtp_configured():
        return 0
    footer = f"\n—\nYou receive this because you are in a CloudMindra workspace. Choose which alerts you get: {settings_link(org_id)}\n"
    for to in recipients:
        jobs.enqueue(db, "notify.email", {"to": to, "subject": subject, "body": body + footer, "event_key": event_key},
                     org_id=org_id, app_key="core", dedupe_key=f"notify:{dedupe}:{to}")
    return len(recipients)


@jobs.job_handler("notify.email")
def _send_email(db: Session, payload: dict, job) -> dict:
    if not send_alert_email(payload["to"], payload["subject"], payload["body"]):
        raise DeliveryFailed(f"{payload['event_key']}: could not email {payload['to']}")
    return {"sent_to": payload["to"]}
