from __future__ import annotations

import html
import smtplib
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from urllib.parse import urlencode

from app.core.config import settings


def _frontend_url(path: str, **query: str) -> str:
    base = settings.FRONTEND_BASE_URL.rstrip("/")
    clean_path = path if path.startswith("/") else f"/{path}"
    suffix = f"?{urlencode(query)}" if query else ""
    return f"{base}{clean_path}{suffix}"


def _sender() -> str:
    configured = settings.SMTP_FROM or settings.SMTP_USERNAME or "no-reply@attendio.local"
    name, address = parseaddr(configured)
    return formataddr((name or settings.APP_NAME, address)) if address else configured


def _template(*, title: str, preview: str, button_label: str, button_url: str, note: str) -> tuple[str, str]:
    safe_title = html.escape(title)
    safe_preview = html.escape(preview)
    safe_button_label = html.escape(button_label)
    safe_button_url = html.escape(button_url, quote=True)
    safe_note = html.escape(note)
    text = f"{title}\n\n{preview}\n\n{button_label}: {button_url}\n\n{note}"
    html_body = f"""\
<!doctype html>
<html>
  <body style="margin:0;background:#f6f8fb;font-family:Arial,Helvetica,sans-serif;color:#0f172a;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f8fb;padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border:1px solid #dbeafe;border-radius:18px;overflow:hidden;">
            <tr>
              <td style="padding:28px 28px 8px;">
                <div style="font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#2563eb;">Attendio</div>
                <h1 style="margin:14px 0 10px;font-size:24px;line-height:1.25;color:#0f172a;">{safe_title}</h1>
                <p style="margin:0;font-size:15px;line-height:1.7;color:#475569;">{safe_preview}</p>
              </td>
            </tr>
            <tr>
              <td style="padding:24px 28px;">
                <a href="{safe_button_url}" style="display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:13px 20px;border-radius:12px;">{safe_button_label}</a>
              </td>
            </tr>
            <tr>
              <td style="padding:0 28px 28px;">
                <p style="margin:0;font-size:13px;line-height:1.6;color:#64748b;">{safe_note}</p>
                <p style="margin:16px 0 0;font-size:12px;line-height:1.6;color:#94a3b8;word-break:break-all;">If the button does not work, open this link:<br>{safe_button_url}</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""
    return text, html_body


def send_email(*, to_email: str, subject: str, text_body: str, html_body: str):
    if not settings.SMTP_HOST:
        raise RuntimeError("SMTP is not configured")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = _sender()
    message["To"] = to_email
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    if settings.SMTP_PORT == 465:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
            smtp.send_message(message)
        return
    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USERNAME:
            smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD or "")
        smtp.send_message(message)


def render(payload: dict) -> tuple[str, str, str]:
    key = payload.get("template_key")
    first_name = payload.get("first_name") or "there"
    metadata = payload.get("metadata") or payload
    if key == "email_verification":
        url = _frontend_url("/verify-email", token=metadata.get("token", ""))
        text, html_body = _template(
            title=f"Verify your email, {first_name}",
            preview="Confirm this email address to activate your Attendio workspace account.",
            button_label="Verify email",
            button_url=url,
            note="This secure link expires soon. If you did not create this account, you can ignore this email.",
        )
        return "Verify your Attendio email", text, html_body
    if key == "password_reset":
        url = _frontend_url("/reset-password", token=metadata.get("token", ""))
        text, html_body = _template(
            title=f"Reset your password, {first_name}",
            preview="Use this secure link to choose a new password for your Attendio account.",
            button_label="Reset password",
            button_url=url,
            note="If you did not request a reset, no action is needed.",
        )
        return "Reset your Attendio password", text, html_body
    if key == "security":
        title = payload["title"]
        text, html_body = _template(
            title=title,
            preview=payload["body"],
            button_label="Review security",
            button_url=_frontend_url("/profilePage"),
            note="If this was not you, change your password and revoke active sessions immediately.",
        )
        return f"Attendio security alert: {title}", text, html_body
    if key == "mfa_reminder":
        deadline = metadata.get("deadline")
        suffix = f" Complete enrollment by {deadline}." if deadline else ""
        text, html_body = _template(
            title=f"Set up MFA, {first_name}",
            preview=f"Your company asks you to protect your Attendio account with multi-factor authentication.{suffix}",
            button_label="Set up MFA",
            button_url=_frontend_url("/profilePage"),
            note="Sign in, open Preferences, and scan the MFA QR code with an authenticator app. Attendio will never email your authenticator secret or one-time codes.",
        )
        return "Set up MFA for your Attendio account", text, html_body
    if key == "test":
        text, html_body = _template(
            title=f"Email delivery test, {first_name}",
            preview="Your Attendio email delivery configuration is working.",
            button_label="Open Attendio",
            button_url=_frontend_url("/dashboard"),
            note="This is only a test email requested from your account settings.",
        )
        return "Attendio email delivery test", text, html_body
    title = payload.get("title", "Attendio notification")
    body = payload.get("body", "")
    text, html_body = _template(
        title=title,
        preview=body,
        button_label="Open Attendio",
        button_url=_frontend_url("/dashboard"),
        note="You are receiving this because this notification is enabled for your account.",
    )
    return title, text, html_body
