"""Outgoing mail, a port with two backends. `resend` posts to the Resend API. `log` writes the message to the server
log, for development, and only when FOODDB__BACKEND__MAIL=log is set explicitly: a sign-in link in a log is a sign-in."""

import logging
import os

import httpx

log = logging.getLogger(__name__)


def backend() -> str | None:
    return os.environ.get("FOODDB__BACKEND__MAIL") or ("resend" if os.environ.get("FOODDB__BACKEND__RESEND_API_KEY") else None)


def configured() -> bool:
    return backend() in ("resend", "log")


def send(to: str, subject: str, body: str) -> None:
    match backend():
        case "log":
            log.info("mail to %s: %s\n%s", to, subject, body)
        case "resend":
            key = os.environ.get("FOODDB__BACKEND__RESEND_API_KEY")
            sender = os.environ.get("FOODDB__BACKEND__MAIL_FROM")
            if not key or not sender:
                raise RuntimeError("set FOODDB__BACKEND__RESEND_API_KEY and FOODDB__BACKEND__MAIL_FROM")
            httpx.post("https://api.resend.com/emails", headers={"Authorization": f"Bearer {key}"}, timeout=15,
                       json={"from": sender, "to": [to], "subject": subject, "text": body}).raise_for_status()
        case _:
            raise RuntimeError("no mail backend: set FOODDB__BACKEND__RESEND_API_KEY (or FOODDB__BACKEND__MAIL=log for development)")
