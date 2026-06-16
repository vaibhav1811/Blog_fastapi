import logging
from email.message import EmailMessage

import aiosmtplib # Asynchronous SMTP client library
from aiosmtplib.errors import SMTPException
import httpx
from fastapi.templating import Jinja2Templates # For rendering email templates

from config import settings

logger = logging.getLogger(__name__)

templates = Jinja2Templates(directory="templates") # Directory for email templates

async def send_email_via_resend(
    to_email: str,
    subject: str,
    plain_text: str,
    html_content: str | None = None,
) -> None:
    """
    Send email via Resend REST API (https://resend.com).

    Notes:
      - follow_redirects=False is intentional: an invalid API key causes Resend to
        return a redirect, and httpx would re-issue the request as GET, resulting in
        a misleading '405 Method Not Allowed'. Keeping redirects off surfaces the
        real error (401 Unauthorized) immediately.
      - Response body is logged before raise_for_status so the Resend error message
        (e.g. "API key is invalid") is always visible in application logs.
    """
    api_key = settings.resend_api_key
    if not api_key or not api_key.get_secret_value():
        raise ValueError(
            "RESEND_API_KEY is not configured. "
            "Set a valid key in your .env file (local) or as an environment variable (production)."
        )

    headers = {
        "Authorization": f"Bearer {api_key.get_secret_value()}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": settings.mail_from,
        "to": [to_email],
        "subject": subject,
        "text": plain_text,
    }
    if html_content:
        payload["html"] = html_content

    # follow_redirects=False prevents httpx from converting POST → GET on redirect
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            json=payload,
            headers=headers,
        )
        if response.is_error:
            logger.error(
                "Resend API error %s for %s — response body: %s",
                response.status_code,
                to_email,
                response.text,
            )
        response.raise_for_status()


async def _send_email_via_brevo_api(
    to_email: str,
    subject: str,
    plain_text: str,
    html_content: str | None = None,
) -> None:
    """Send email using Brevo (Sendinblue) Transactional Email API."""
    headers = {
        "accept": "application/json",
        "api-key": settings.brevo_api_key.get_secret_value(),  # type: ignore[union-attr]
        "content-type": "application/json",
    }
    payload = {
        "sender": {"email": settings.mail_from},
        "to": [{"email": to_email}],
        "subject": subject,
        "textContent": plain_text,
    }
    if html_content:
        payload["htmlContent"] = html_content

    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(
            "https://api.brevo.com/v3/smtp/email",
            json=payload,
            headers=headers,
        )
        if response.is_error:
            logger.error(
                "Brevo API error %s for %s — response body: %s",
                response.status_code,
                to_email,
                response.text,
            )
        response.raise_for_status()


async def send_email(
    to_email: str,
    subject: str,
    plain_text: str,
    html_content: str | None = None,
) -> None:
    """
    Unified email dispatcher with priority fallback:
      1. Resend API  (if RESEND_API_KEY is set)
      2. Brevo API   (if BREVO_API_KEY is set)
      3. SMTP        (fallback using MAIL_SERVER / MAIL_PORT credentials)
    """
    # --- Priority 1: Resend ---
    if settings.resend_api_key and settings.resend_api_key.get_secret_value():
        logger.info("Sending email via Resend to %s", to_email)
        await send_email_via_resend(
            to_email=to_email,
            subject=subject,
            plain_text=plain_text,
            html_content=html_content,
        )
        return

    # --- Priority 2: Brevo API ---
    if settings.brevo_api_key and settings.brevo_api_key.get_secret_value():
        logger.info("Sending email via Brevo API to %s", to_email)
        await _send_email_via_brevo_api(
            to_email=to_email,
            subject=subject,
            plain_text=plain_text,
            html_content=html_content,
        )
        return

    # --- Priority 3: SMTP fallback ---
    logger.info("Sending email via SMTP to %s", to_email)
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to_email
    message["Subject"] = subject

    message.set_content(plain_text)

    if html_content:
        message.add_alternative(html_content, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.mail_server,
            port=settings.mail_port,
            username=settings.mail_username if settings.mail_username else None,
            password=settings.mail_password.get_secret_value() or None,
            start_tls=settings.mail_use_tls,
        )
    except SMTPException as exc:
        logger.exception(
            "SMTP email send failed: %s. Check MAIL_SERVER, MAIL_PORT, MAIL_USERNAME, MAIL_PASSWORD.",
            exc,
        )
        raise
    except OSError as exc:
        logger.exception(
            "Network error while sending email: %s. Verify SMTP host/port connectivity.",
            exc,
        )
        raise

## send_password_reset_email function
async def send_password_reset_email(to_email: str, username: str, token: str) -> None:
    reset_url = f"{settings.frontend_url}/reset-password?token={token}"

    template = templates.env.get_template("email/password_reset.html") # Load the email template for password reset
    html_content = template.render(reset_url=reset_url, username=username)

    plain_text = f"""Hi {username},

You requested to reset your password. Click the link below to set a new password:

{reset_url}

This link will expire in 1 hour.

If you didn't request this, you can safely ignore this email.

Best regards,
The FastAPI Blog Team
"""

    try:
        await send_email(
            to_email=to_email,
            subject="Reset Your Password - FastAPI Blog",
            plain_text=plain_text,
            html_content=html_content,
        )
    except Exception as exc:
        logger.exception(
            "Failed to send password reset email to %s: %s",
            to_email,
            exc,
        )
