"""SMTP invitation delivery. Never log recipients, invitation tokens or credentials."""
import html
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote, urlsplit

from fastapi import HTTPException
from app.backend.core.config import settings


def send_invitation(email: str, token: str):
    if not settings.smtp_host:
        raise HTTPException(503, "Отправка почты не настроена: задайте SMTP в .env")
    url = urlsplit(settings.public_app_url)
    if url.scheme not in {"http", "https"} or not url.netloc or url.fragment or url.query:
        raise HTTPException(503, "Настройте PUBLIC_APP_URL для приглашений")
    if settings.smtp_security not in {"ssl", "starttls", "none"}:
        raise HTTPException(503, "Недопустимый режим SMTP_SECURITY")
    link = settings.public_app_url.rstrip("/") + "/#invite=" + quote(token, safe="")
    message = EmailMessage()
    message["Subject"] = "Приглашение в Clinical Compass"
    message["From"] = settings.smtp_from
    message["To"] = email
    message.set_content(f"Вас пригласили в Clinical Compass.\nПринять приглашение: {link}\n"
                        "Ссылка действует 48 часов. Войдите или зарегистрируйтесь с этим email.")
    message.add_alternative(
        '<p>Вас пригласили в Clinical Compass.</p>'
        f'<p><a href="{html.escape(link, quote=True)}">Принять приглашение</a></p>'
        '<p>Ссылка действует 48 часов. Войдите или зарегистрируйтесь с этим email.</p>', subtype="html")
    smtp = smtplib.SMTP_SSL if settings.smtp_security == "ssl" else smtplib.SMTP
    options = {"timeout": 15}
    if settings.smtp_security == "ssl":
        options["context"] = ssl.create_default_context()
    try:
        with smtp(settings.smtp_host, settings.smtp_port, **options) as server:
            if settings.smtp_security == "starttls":
                server.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                if settings.smtp_security == "none":
                    raise HTTPException(503, "Для авторизации SMTP требуется TLS")
                server.login(settings.smtp_username, settings.smtp_password)
            refused = server.send_message(message)
            if refused:
                raise smtplib.SMTPRecipientsRefused(refused)
    except (smtplib.SMTPException, OSError):
        raise HTTPException(502, "Не удалось отправить приглашение. Проверьте настройки почты и повторите.") from None
