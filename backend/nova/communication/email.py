"""Email through classic Outlook (COM automation) when an Outlook profile exists; otherwise a draft is opened in
the default mail app (mailto:) and the user presses Send there. NOVA never claims a send it could not verify.
"""

from __future__ import annotations

import os
import time
import winreg
from pathlib import Path
from urllib.parse import quote

OL_MAIL_ITEM = 0
OL_FOLDER_SENT = 5
OL_FOLDER_OUTBOX = 4
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024


class MailError(Exception):
    """Roman Urdu reason."""


class Mailer:
    """The real machine. Tests substitute a fake with the same methods."""

    def outlook_ready(self) -> bool:
        for version in ("16.0", "15.0"):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, rf"Software\Microsoft\Office\{version}\Outlook\Profiles") as k:
                    if winreg.QueryInfoKey(k)[0] > 0:  # at least one mail profile is set up
                        return True
            except OSError:
                continue
        return False

    @staticmethod
    def _outlook():
        import comtypes
        import comtypes.client

        comtypes.CoInitialize()
        try:
            return comtypes.client.CreateObject("Outlook.Application", dynamic=True)
        except OSError as exc:
            raise MailError("Outlook shuru nahi ho saka") from exc

    def send_outlook(self, to: str, subject: str, body: str, attachments: list[Path]) -> str:
        """Returns "sent" (found in Sent Items), "outbox" (queued, not yet sent) or "unknown"."""
        app = self._outlook()
        mail = app.CreateItem(OL_MAIL_ITEM)
        mail.To, mail.Subject, mail.Body = to, subject, body
        for path in attachments:
            mail.Attachments.Add(str(path))
        mail.Send()
        session = app.GetNamespace("MAPI")
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self._has_subject(session.GetDefaultFolder(OL_FOLDER_SENT), subject):
                return "sent"
            time.sleep(1.5)
        return "outbox" if self._has_subject(session.GetDefaultFolder(OL_FOLDER_OUTBOX), subject) else "unknown"

    @staticmethod
    def _has_subject(folder, subject: str) -> bool:
        items = folder.Items
        items.Sort("[CreationTime]", True)  # newest first
        for n in range(1, min(items.Count, 15) + 1):
            if str(items.Item(n).Subject) == subject:
                return True
        return False

    def draft_outlook(self, to: str, subject: str, body: str, attachments: list[Path]) -> bool:
        app = self._outlook()
        mail = app.CreateItem(OL_MAIL_ITEM)
        mail.To, mail.Subject, mail.Body = to, subject, body
        for path in attachments:
            mail.Attachments.Add(str(path))
        mail.Save()
        mail.Display(False)
        return bool(mail.EntryID)

    def open_mailto(self, to: str, subject: str, body: str) -> None:
        url = f"mailto:{quote(to, safe='@')}?subject={quote(subject)}&body={quote(body[:1800])}"
        os.startfile(url)  # noqa: S606 - the default mail app shows the draft; the user sends it
