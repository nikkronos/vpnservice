"""
Отправка OTP-кодов через Resend API.
Документация: https://resend.com/docs/api-reference/emails/send-email
"""

import json
import logging
import random
import string
from typing import Optional

import requests as _requests

logger = logging.getLogger(__name__)

RESEND_API_URL = "https://api.resend.com/emails"


def generate_otp(length: int = 6) -> str:
    """Генерирует числовой OTP-код."""
    return "".join(random.choices(string.digits, k=length))


def send_otp_email(
    to_email: str,
    code: str,
    api_key: str,
    from_email: str = "noreply@vpn.example.com",
    service_name: str = "VPN",
) -> bool:
    """
    Отправляет OTP-код на email через Resend API.
    Возвращает True при успехе, False при ошибке.
    """
    subject = f"Код подтверждения — {service_name}"
    html_body = f"""
    <!DOCTYPE html>
    <html lang="ru">
    <body style="font-family:system-ui,sans-serif;max-width:480px;margin:40px auto;padding:0 24px;color:#1a1a1a;">
      <h2 style="margin:0 0 8px;">Ваш код входа</h2>
      <p style="color:#555;margin:0 0 24px;">Введите его на странице восстановления VPN.</p>
      <div style="background:#f4f4f5;border-radius:12px;padding:24px;text-align:center;">
        <span style="font-size:40px;font-weight:700;letter-spacing:12px;font-family:monospace;">{code}</span>
      </div>
      <p style="color:#888;font-size:13px;margin:24px 0 0;">Код действует 10 минут.<br>
      Если вы не запрашивали его — просто проигнорируйте письмо.</p>
    </body>
    </html>
    """

    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "html": html_body,
    }

    try:
        resp = _requests.post(
            RESEND_API_URL,
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=15,
        )
        if resp.status_code in (200, 201):
            logger.info("OTP отправлен на %s", to_email)
            return True
        logger.error("Resend HTTP %s для %s: %s", resp.status_code, to_email, resp.text[:300])
        return False
    except _requests.RequestException as e:
        logger.error("Resend сетевая ошибка для %s: %s", to_email, e)
        return False
    except Exception as e:  # noqa: BLE001
        logger.exception("Неожиданная ошибка при отправке OTP на %s: %s", to_email, e)
        return False
