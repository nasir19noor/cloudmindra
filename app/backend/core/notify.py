"""Notifications to workspace members (DESIGN.md §7).

Called from event handlers (jobs), so a failed send is retried by the job queue.
Per-person preferences (core.notification_prefs) arrive in phase 4; until then every
member receives every workspace alert (DESIGN.md §4.1).
"""
from sqlalchemy.orm import Session

from core.mailer import send_alert_email, smtp_configured
from core.orgs import alert_recipients


class DeliveryFailed(RuntimeError):
    """Raised so the job is retried."""


def notify(db: Session, org_id: str, event_key: str, subject: str, body: str) -> int:
    """Email everyone in the workspace. Returns the number of emails sent."""
    recipients = alert_recipients(db, org_id)
    if not recipients or not smtp_configured():
        return 0
    failed = [to for to in recipients if not send_alert_email(to, subject, body)]
    if failed:
        raise DeliveryFailed(f"{event_key}: could not email {len(failed)} of {len(recipients)} recipients")
    return len(recipients)
