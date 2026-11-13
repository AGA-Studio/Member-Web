"""Sends email: today only the card link (API contract, section 13.7).

- With `SMTP_HOST`: real SMTP, with the TLS mode of `SMTP_TLS` (for example
  Mailpit in development).
- Without it: in development the message is logged and kept in `OUTBOX` (the
  last 50), so the flow works with no provider; in production the send fails.

`deliver` never holds the request for more than `SEND_DEADLINE_SECONDS`: the
send runs in a worker thread. If it has not finished by then the result is
`pending` and it carries on in the background (a later failure is only logged).
"""

import logging
import smtplib
import ssl
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from email.message import EmailMessage
from enum import StrEnum

from core.config import settings

SEND_DEADLINE_SECONDS = 1.5
OUTBOX_SIZE = 50

# uvicorn's logger is the one that reaches the console when the API runs.
logger = logging.getLogger("uvicorn.error")

OUTBOX: deque[EmailMessage] = deque(maxlen=OUTBOX_SIZE)
_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="mail")


class SendResult(StrEnum):
    SENT = "sent"
    FAILED = "failed"
    PENDING = "pending"


class NoProviderError(RuntimeError):
    """No SMTP provider is configured outside development."""


def _send_smtp(message: EmailMessage) -> None:
    timeout = settings.smtp_timeout_seconds
    if settings.smtp_tls == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=timeout)
    with client:
        if settings.smtp_tls == "starttls":
            client.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)


def send(message: EmailMessage) -> None:
    """Send now, in this thread. Raises if the message could not be delivered."""
    if settings.smtp_host:
        _send_smtp(message)
        return
    if settings.environment != "development":
        raise NoProviderError("SMTP_HOST is not configured")
    OUTBOX.append(message)
    logger.info(
        "Email not sent (no SMTP_HOST): to=%s subject=%s", message["To"], message["Subject"]
    )


def _send_logged(message: EmailMessage) -> None:
    try:
        send(message)
    except Exception:
        logger.exception("Email to %s failed", message["To"])
        raise


def deliver(message: EmailMessage, deadline: float = SEND_DEADLINE_SECONDS) -> SendResult:
    """Send without holding the caller more than `deadline` seconds. Never raises."""
    future = _executor.submit(_send_logged, message)
    try:
        future.result(timeout=deadline)
    except FutureTimeout:
        return SendResult.PENDING
    except Exception:
        return SendResult.FAILED
    return SendResult.SENT
