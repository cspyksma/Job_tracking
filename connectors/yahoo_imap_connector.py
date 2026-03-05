from __future__ import annotations

import email
import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any


LOGGER = logging.getLogger(__name__)


def _decode_subject(raw: str | None) -> str:
    if not raw:
        return ""
    decoded = email.header.decode_header(raw)
    parts = []
    for value, charset in decoded:
        if isinstance(value, bytes):
            parts.append(value.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(value)
    return "".join(parts).strip()


def _extract_plain_body(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            dispo = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in dispo.lower():
                payload = part.get_payload(decode=True) or b""
                charset = part.get_content_charset() or "utf-8"
                return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def _clean_text(text: str) -> str:
    text = re.sub(r"\r\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    markers = ["\nOn ", "\nFrom:", "\n-----Original Message-----"]
    lower = text.lower()
    cut_idx = len(text)
    for marker in markers:
        idx = lower.find(marker.lower())
        if idx != -1:
            cut_idx = min(cut_idx, idx)
    return text[:cut_idx].strip()


def _parse_from(raw_from: str) -> tuple[str, str, str]:
    _, addr = email.utils.parseaddr(raw_from or "")
    name = raw_from.replace(addr, "").strip().strip("<>").strip('"').strip()
    domain = addr.split("@", 1)[1].lower() if "@" in addr else ""
    return name, addr.lower(), domain


def _normalize_message_id(message_id: str | None, uid: int) -> str:
    if message_id:
        return message_id.strip().strip("<>").lower()
    return f"imap-uid-{uid}"


def _parse_uidvalidity_from_status(data: list[bytes]) -> int:
    if not data:
        return 0
    text = b" ".join(d for d in data if isinstance(d, (bytes, bytearray))).decode("utf-8", errors="ignore")
    m = re.search(r"UIDVALIDITY\s+(\d+)", text, re.IGNORECASE)
    return int(m.group(1)) if m else 0


class YahooIMAPConnector:
    def __init__(self, host: str, port: int, username: str, app_password: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.app_password = app_password

    def _connect(self) -> imaplib.IMAP4_SSL:
        client = imaplib.IMAP4_SSL(self.host, self.port)
        client.login(self.username, self.app_password)
        return client

    def list_folders(self) -> list[str]:
        client = self._connect()
        try:
            status, data = client.list()
            if status != "OK" or not data:
                return []
            folders: list[str] = []
            for entry in data:
                if not entry:
                    continue
                line = entry.decode("utf-8", errors="ignore")
                # Last token is mailbox name, often quoted.
                name = line.split(" ", 2)[-1].strip().strip('"')
                folders.append(name)
            return folders
        finally:
            try:
                client.logout()
            except Exception:
                LOGGER.debug("IMAP logout failed", exc_info=True)

    def fetch_incremental_messages(
        self,
        folder: str,
        last_seen_uid: int,
        known_uidvalidity: int,
        since_days: int,
        max_messages: int,
    ) -> dict[str, Any]:
        """
        Fetches messages for one folder with UID-based incremental behavior.
        Returns dict with uidvalidity, last_seen_uid_effective, and messages[].
        """
        client = self._connect()
        try:
            status, _ = client.select(folder, readonly=True)
            if status != "OK":
                raise RuntimeError(f"Unable to select folder: {folder}")

            status, sdata = client.status(folder, "(UIDVALIDITY)")
            if status != "OK":
                raise RuntimeError(f"Unable to get UIDVALIDITY for folder: {folder}")
            uidvalidity = _parse_uidvalidity_from_status(sdata)
            effective_last_uid = last_seen_uid
            uidvalidity_reset = False
            if known_uidvalidity and uidvalidity and int(known_uidvalidity) != int(uidvalidity):
                # Folder got recreated/reset; start from scratch for this folder.
                effective_last_uid = 0
                uidvalidity_reset = True

            if effective_last_uid > 0:
                criteria = f"(UID {effective_last_uid + 1}:*)"
            elif uidvalidity_reset:
                criteria = "(UID 1:*)"
            else:
                since_date = (datetime.now(timezone.utc) - timedelta(days=since_days)).strftime("%d-%b-%Y")
                criteria = f'(SINCE "{since_date}")'

            status, data = client.uid("search", None, criteria)
            if status != "OK":
                return {"uidvalidity": uidvalidity, "messages": [], "last_seen_uid_effective": effective_last_uid}
            uids = [u for u in (data[0].split() if data and data[0] else []) if u]
            if not uids:
                return {"uidvalidity": uidvalidity, "messages": [], "last_seen_uid_effective": effective_last_uid}
            uids = uids[-max_messages:]

            messages: list[dict[str, Any]] = []
            for uid_bytes in uids:
                uid = int(uid_bytes)
                status, payload = client.uid("fetch", uid_bytes, "(RFC822)")
                if status != "OK" or not payload or payload[0] is None:
                    continue
                raw_bytes = payload[0][1]
                msg = email.message_from_bytes(raw_bytes)
                subject = _decode_subject(msg.get("Subject"))
                body = _clean_text(_extract_plain_body(msg))
                date_val = msg.get("Date")
                internal_date = parsedate_to_datetime(date_val) if date_val else datetime.now(timezone.utc)
                if internal_date.tzinfo is None:
                    internal_date = internal_date.replace(tzinfo=timezone.utc)
                from_name, from_email, from_domain = _parse_from(msg.get("From", ""))
                message_id = _normalize_message_id(msg.get("Message-ID"), uid)
                messages.append(
                    {
                        "uid": uid,
                        "message_id_header": message_id,
                        "subject": subject,
                        "body": body,
                        "from_name": from_name,
                        "from_email": from_email,
                        "from_domain": from_domain,
                        "internal_date": internal_date,
                        "references": msg.get("References", ""),
                        "in_reply_to": msg.get("In-Reply-To", ""),
                    }
                )
            return {
                "uidvalidity": uidvalidity,
                "messages": messages,
                "last_seen_uid_effective": effective_last_uid,
            }
        finally:
            try:
                client.logout()
            except Exception:
                LOGGER.debug("IMAP logout failed", exc_info=True)
