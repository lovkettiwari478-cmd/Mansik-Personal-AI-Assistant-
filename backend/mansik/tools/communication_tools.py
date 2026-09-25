"""Communication tools — in-app notifications (always real) and email
(SMTP-gated; unavailable without real credentials — never faked)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

from ..config import RISK_EXTERNAL_COMM, RISK_LOW_WRITE, get_settings
from ..errors import AppError, ValidationAppError
from ..models import Notification, new_id, utcnow
from .base import Tool, ToolContext, ToolParams
from pydantic import Field, field_validator


class NotifyParams(ToolParams):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field("", max_length=2000)
    kind: str = Field("info", pattern="^(info|warning|action|reminder)$")


class EmailParams(ToolParams):
    to: str = Field(..., min_length=3, max_length=320)
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=20000)

    @field_validator("to")
    @classmethod
    def _basic_email(cls, v: str) -> str:
        if "@" not in v or v.startswith("@") or v.endswith("@") or " " in v:
            raise ValidationAppError("Invalid recipient address.")
        return v


class NotifyTool(Tool):
    id = "notify.user"
    name = "Notify me"
    description = "Create an in-app notification for the user (info, warning, action or reminder)."
    category = "communication"
    risk = RISK_LOW_WRITE
    scope = "notify"
    timeout_seconds = 10.0
    params_model = NotifyParams

    async def run(self, ctx: ToolContext, params: NotifyParams) -> dict:
        notification = Notification(
            id=new_id(), user_id=ctx.user.id, kind=params.kind,
            title=params.title, body=params.body, created_at=utcnow(),
        )
        ctx.db.add(notification)
        ctx.db.flush()
        return {"notification": {"id": notification.id, "title": notification.title, "kind": notification.kind}}


class EmailTool(Tool):
    id = "email.send"
    name = "Send email"
    description = "Send an email via the configured SMTP account. Every send requires confirmation and is audited."
    category = "communication"
    risk = RISK_EXTERNAL_COMM
    scope = "email:send"
    timeout_seconds = 25.0
    params_model = EmailParams

    def available(self, ctx: ToolContext) -> bool:
        s = get_settings()
        return bool(s.smtp_host and s.smtp_from)

    def unavailable_reason(self) -> str:
        return "Email is not configured — set MANISK_SMTP_HOST, MANISK_SMTP_USER, MANISK_SMTP_PASSWORD, MANISK_SMTP_FROM."

    async def run(self, ctx: ToolContext, params: EmailParams) -> dict:
        s = get_settings()

        def _send():
            msg = EmailMessage()
            msg["From"] = s.smtp_from
            msg["To"] = params.to
            msg["Subject"] = params.subject
            msg.set_content(params.body)
            if s.smtp_starttls:
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as server:
                    server.starttls()
                    if s.smtp_user and s.smtp_password:
                        server.login(s.smtp_user, s.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20) as server:
                    if s.smtp_user and s.smtp_password:
                        server.login(s.smtp_user, s.smtp_password)
                    server.send_message(msg)

        try:
            await self.run_sync(_send)
        except (smtplib.SMTPException, OSError) as exc:
            raise AppError(f"SMTP delivery failed: {type(exc).__name__}.", code="smtp_error")
        return {"sent": True, "to": params.to, "subject": params.subject}
