import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


def _clean_header(value: str) -> str:
    # Prevent header injection via CR/LF in user-supplied values
    return " ".join(value.splitlines()).strip()


def send_contact_email(name: str, email: str, company: str | None, message: str) -> None:
    """Forward a contact form submission to the CloudMindra inbox via Amazon SES SMTP."""
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME")
    password = os.getenv("SMTP_PASSWORD")
    secure = _env_bool("SMTP_SECURE")  # true: implicit TLS (465); false: STARTTLS (587)
    ignore_tls = _env_bool("SMTP_IGNORETLS")
    mail_from = os.getenv("MAIL_FROM_ADDRESS", "hi@cloudmindra.com")
    mail_to = os.getenv("MAIL_TO_ADDRESS", mail_from)

    if not host or not username or not password:
        logger.warning("SMTP is not configured; skipping contact email")
        return

    name = _clean_header(name)
    company = _clean_header(company) if company else None

    msg = EmailMessage()
    msg["From"] = formataddr(("CloudMindra Website", mail_from))
    msg["To"] = mail_to
    msg["Reply-To"] = formataddr((name, email))
    msg["Subject"] = f"New inquiry from {name}" + (f" ({company})" if company else "")
    msg.set_content(
        f"Name: {name}\n"
        f"Email: {email}\n"
        f"Company: {company or '-'}\n"
        f"\n{message}\n"
    )

    context = ssl.create_default_context()
    try:
        if secure:
            with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as smtp:
                smtp.login(username, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                if not ignore_tls:
                    smtp.starttls(context=context)
                smtp.login(username, password)
                smtp.send_message(msg)
        logger.info("Contact email sent for %s", email)
    except Exception:
        logger.exception("Failed to send contact email for %s", email)
