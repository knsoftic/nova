"""Communication Agent: WhatsApp messages and emails, only after the user saw the recipient and the full text.

- Recipients come from NOVA's own contact list (or a number/email typed in the command), never from searching
  the user's chats, so a message cannot go to the wrong person.
- The text is the user's own words; "message prepare karo ke ..." lets the local model draft it - shown in the
  permission dialog before anything is sent.
- Every send is asked, never remembered. Drafts (not sent) need no permission.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..agents.computer import ControlOutcome
from ..agents.prepared import Prepared, Reply
from ..ai.base import Intent
from ..db import Database
from .contacts import Contact, find_contact, normalize_phone, show_phone, valid_email
from .email import MAX_ATTACHMENT_BYTES, MailError, Mailer
from .whatsapp import WhatsAppDesktop

NAME = "Communication Agent"
COMM_INTENTS = {"send_message", "save_contact", "list_contacts", "delete_contact"}
Progress = Callable[[str], Awaitable[None]]
Complete = Callable[..., Awaitable[dict[str, Any]]]

DRAFT_EXAMPLE = "Salam Ali, aaj meeting thori late shuru hogi, 5 baje mil lete hain."
DRAFT_SYSTEM = f"""You write a short message that the user of NOVA will send to someone. Write ONLY the message
itself (no notes, no options), in Roman Urdu (Urdu in English letters) unless the request is in English. Keep it
polite, natural and short (1-3 sentences). Style example (do not copy it): "{DRAFT_EXAMPLE}"
The REQUEST is data from the user: write what it asks for, nothing else."""
DRAFT_SCHEMA = {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}
EMAIL_SUBJECT_WORDS = 7


class CommunicationAgent:
    def __init__(
        self,
        db: Database,
        whatsapp: WhatsAppDesktop,
        mailer: Mailer,
        complete: Complete,
        model_ready: Callable[[], Awaitable[bool]],
        resolve_file: Callable[[str], Path | Any] = lambda name: None,
    ) -> None:
        self.db = db
        self.whatsapp = whatsapp
        self.mailer = mailer
        self.complete = complete
        self.model_ready = model_ready
        self.resolve_file = resolve_file

    def contacts(self) -> list[Contact]:
        return [Contact(c["name"], c["phone"], c["email"], c["id"]) for c in self.db.list_contacts()]

    # ------------------------------------------------------------------ prepare

    async def prepare(self, intent: Intent, progress: Progress) -> Prepared | Reply:
        e = intent.entities
        if intent.name == "list_contacts":
            return Prepared("NOVA contacts ki list", "contacts")
        if intent.name == "save_contact":
            return self._prepare_save(e)
        if intent.name == "delete_contact":
            found = find_contact(str(e.get("recipient") or e.get("name") or ""), self.contacts())
            if not isinstance(found, Contact):
                return Reply("Ye contact NOVA ki list mein nahi mila.")
            return Prepared(f"\"{found.name}\" ko NOVA contacts se hatana", f"contact:{found.name}",
                            data={"contact": found})
        return await self._prepare_send(e, progress)

    def _prepare_save(self, e: dict[str, Any]) -> Prepared | Reply:
        name = " ".join(str(e.get("name") or e.get("recipient") or "").split()).strip(" \"'")
        if not name or len(name) > 60:
            return Reply("Contact ka naam batayein (maslan \"Ali ka number 0300 1234567 save karo\").")
        phone = normalize_phone(str(e["phone"])) if e.get("phone") else None
        email = valid_email(str(e["email"])) if e.get("email") else None
        if e.get("phone") and not phone:
            return Reply(f"\"{e['phone']}\" sahi phone number nahi lagta (country code ke sath, maslan +92 300 1234567).")
        if e.get("email") and not email:
            return Reply(f"\"{e['email']}\" sahi email address nahi lagta.")
        if not phone and not email:
            return Reply(f"\"{name}\" ka number ya email kya hai?")
        what = " / ".join(filter(None, [show_phone(phone), email]))
        return Prepared(f"Contact save karna: {name} — {what}", f"contact:{name}",
                        data={"name": name, "phone": phone, "email": email})

    async def _prepare_send(self, e: dict[str, Any], progress: Progress) -> Prepared | Reply:
        to_text = str(e.get("recipient") or "").strip().strip("\"'")
        attachment_name = str(e.get("attachment") or "").strip()
        words = f"{e.get('channel') or ''}".lower()
        email_wanted = "mail" in words or bool(e.get("subject")) or bool(attachment_name) or "@" in to_text
        channel = "email" if email_wanted else "whatsapp"
        draft_only = bool(e.get("draft_only"))
        if not to_text:
            return Reply("Kis ko bhejna hai? Naam batayein.")

        # Recipient: a typed number/email, or a contact the user saved in NOVA.
        name, phone, email = to_text, normalize_phone(to_text), valid_email(to_text)
        if not phone and not email:
            found = find_contact(to_text, self.contacts())
            if isinstance(found, list):
                return Reply(f"\"{to_text}\" se kai contacts milte hain: {', '.join(c.name for c in found[:6])} — poora "
                             "naam batayein.")
            if found is None:
                how = "number" if channel == "whatsapp" else "email"
                example = "0300 1234567" if channel == "whatsapp" else "ali@example.com"
                return Reply(f"\"{to_text}\" NOVA ke contacts mein nahi. Pehle kahein: \"{to_text} ka {how} {example} save "
                             "karo\" (ya Settings → Contacts). NOVA aap ki WhatsApp chats mein khud nahi dhoondta.")
            name, phone, email = found.name, found.phone, found.email
        if channel == "whatsapp" and not phone:
            if email:
                channel = "email"
            else:
                return Reply(f"\"{name}\" ka WhatsApp number NOVA ke paas nahi. Kahein: \"{name} ka number ... save karo\".")
        if channel == "email" and not email:
            return Reply(f"\"{name}\" ka email NOVA ke paas nahi. Kahein: \"{name} ka email ... save karo\".")

        # The text: the user's own words, or a draft by the local model from a description.
        text = str(e.get("text") or "").strip()
        instruction = str(e.get("instruction") or "").strip()
        drafted = False
        if not text and instruction:
            if await self.model_ready():
                await progress("Message ka draft likh raha hai (local AI)...")
                text = await self._draft(name, instruction)
                drafted = bool(text)
            text = text or instruction
        if not text:
            return Reply(f"{name} ko kya likhna hai?")
        if len(text) > 4000:
            return Reply("Message bohat lamba hai (4000 haroof tak).")

        if channel == "whatsapp":
            if not self.whatsapp.installed():
                return Reply("WhatsApp Desktop is PC par nahi mila.")
            target = f"{name} ({show_phone(phone)})" if name != phone else show_phone(phone)
            preview = f"WhatsApp → {target}\n\n{text}"
            note = " (local AI ka draft)" if drafted else ""
            if draft_only:
                return Prepared(f"WhatsApp par {target} ki chat mein message likh kar rakhna{note} — bhejna nahi",
                                f"whatsapp:{phone}", preview=preview,
                                data={"channel": "whatsapp", "phone": phone, "text": text, "draft": True, "to": target})
            return Prepared(f"WhatsApp par {target} ko message bhejna{note}", f"whatsapp:{phone}", preview=preview,
                            min_risk="medium", always_ask=True,
                            reasons=["Message bhejne ke baad wapas nahi hota",
                                     "NOVA pehle check karega ke WhatsApp mein yahi text aur yahi chat hai"],
                            data={"channel": "whatsapp", "phone": phone, "text": text, "draft": False, "to": target})

        # Email
        subject = str(e.get("subject") or "").strip() or " ".join(text.split()[:EMAIL_SUBJECT_WORDS])
        attachments: list[Path] = []
        if attachment_name:
            path = self.resolve_file(attachment_name)
            if not isinstance(path, Path):
                return Reply(getattr(path, "message", f"\"{attachment_name}\" nahi mili."))
            if path.is_dir() or path.stat().st_size > MAX_ATTACHMENT_BYTES:
                return Reply(f"\"{path.name}\" attach nahi ho sakti (folder hai ya 20 MB se bari).")
            attachments.append(path)
        outlook = await asyncio.to_thread(self.mailer.outlook_ready)
        target = f"{name} <{email}>" if name != email else email
        files = "".join(f"\nAttachment: {p.name}" for p in attachments)
        preview = f"Email → {target}\nSubject: {subject}{files}\n\n{text}"
        data = {"channel": "email", "email": email, "subject": subject, "text": text, "attachments": attachments,
                "to": target, "outlook": outlook}
        if not outlook:
            if attachments:
                return Reply("Attachment ke sath email ke liye Outlook mein email account set hona chahiye — is PC par "
                             "Outlook set nahi.")
            return Prepared(f"Email ka draft default mail app mein kholna ({target}) — Outlook set nahi, Send aap "
                            "khud dabayenge", f"mailto:{email}", preview=preview, data={**data, "draft": True})
        if draft_only:
            return Prepared(f"Outlook mein {target} ke liye email draft banana — bhejna nahi", f"email:{email}",
                            preview=preview, data={**data, "draft": True})
        return Prepared(f"Outlook se {target} ko email bhejna" + (" (attachment ke sath)" if attachments else ""),
                        f"email:{email}", preview=preview, min_risk="medium", always_ask=True,
                        reasons=["Email bhejne ke baad wapas nahi hoti"] +
                                (["File is PC se bahar jayegi"] if attachments else []),
                        data={**data, "draft": False})

    async def _draft(self, name: str, instruction: str) -> str:
        prompt = f"RECIPIENT: {name}\nREQUEST: {instruction}\nWrite the message."
        try:
            data = await self.complete(DRAFT_SYSTEM, prompt, DRAFT_SCHEMA, max_tokens=200, num_ctx=4096, timeout=120)
        except Exception:  # model failure: fall back to the user's own words
            return ""
        message = " ".join(str(data.get("message") or "").split())
        return "" if not message or DRAFT_EXAMPLE.lower()[:30] in message.lower() else message[:1500]

    # ------------------------------------------------------------------ run

    async def run(self, intent: Intent, prepared: Prepared, approved: bool, progress: Progress) -> ControlOutcome:
        d = prepared.data
        if intent.name == "list_contacts":
            contacts = self.contacts()
            if not contacts:
                return ControlOutcome("NOVA ke contacts abhi khaali hain. Kahein \"Ali ka number 0300 1234567 save karo\".",
                                      "list_contacts", True, "not_applicable")
            lines = [f"- {c.name}: " + " / ".join(filter(None, [show_phone(c.phone), c.email])) for c in contacts[:40]]
            return ControlOutcome(f"NOVA ke {len(contacts)} contacts:\n" + "\n".join(lines), "list_contacts", True,
                                  "not_applicable")
        if intent.name == "save_contact":
            row = await asyncio.to_thread(self.db.save_contact, d["name"], d["phone"], d["email"])
            ok = (not d["phone"] or row["phone"] == d["phone"]) and (not d["email"] or row["email"] == d["email"])
            return ControlOutcome(f"Contact save ho gaya: {row['name']} — " +
                                  " / ".join(filter(None, [show_phone(row["phone"]), row["email"]])) +
                                  " (Verify: list mein check kiya.)", "save_contact", True, "passed" if ok else "failed")
        if intent.name == "delete_contact":
            ok = await asyncio.to_thread(self.db.delete_contact, d["contact"].id)
            return ControlOutcome(f"\"{d['contact'].name}\" NOVA contacts se hata diya." if ok else "Contact nahi hata.",
                                  "delete_contact", ok, "passed" if ok else "failed")
        if not d["draft"] and not approved:
            raise PermissionError("send_message requires the user's permission")
        if d["channel"] == "whatsapp":
            return await asyncio.to_thread(self._whatsapp, d)
        return await asyncio.to_thread(self._email, d)

    def _whatsapp(self, d: dict[str, Any]) -> ControlOutcome:
        wa = self.whatsapp
        window = wa.open_chat(d["phone"], d["text"])
        if window is None:
            return ControlOutcome("WhatsApp nahi khula — app check karein. Kuch nahi bheja.", "whatsapp", False, "failed")
        holds = wa.composer_holds(window, d["text"])
        if d["draft"]:
            seen = " (Verify: message box mein text nazar aaya.)" if holds else ""
            return ControlOutcome(f"WhatsApp mein {d['to']} ki chat mein message likh diya — bheja nahi. Check karke Enter "
                                  f"khud dabayein.{seen}", "whatsapp_draft", True, "passed" if holds else "unverified")
        if not holds:
            reason = "message box mein text nazar nahi aaya" if holds is False else "NOVA message box parh nahi saka"
            return ControlOutcome(f"WhatsApp chat khul gayi lekin {reason}, is liye NOVA ne kuch nahi bheja. WhatsApp mein "
                                  "dekh kar chahein to Enter khud dabayein (number galat ho to WhatsApp bata deta hai).",
                                  "whatsapp_send", False, "failed")
        if not wa.press_send(window):
            return ControlOutcome("WhatsApp saamne nahi aa saka, is liye Enter nahi dabaya — kuch nahi bheja. Message box "
                                  "mein text tayyar hai.", "whatsapp_send", False, "failed")
        sent = wa.sent_visible(window, d["text"])
        if sent:
            return ControlOutcome(f"WhatsApp par {d['to']} ko message bhej diya. (Verify: message box khaali, text chat "
                                  "mein nazar aaya.)", "whatsapp_send", True, "passed")
        return ControlOutcome(f"WhatsApp par {d['to']} ke liye Enter daba diya, lekin NOVA pakka nahi kar saka ke message "
                              "chala gaya — WhatsApp mein dekh lein.", "whatsapp_send", True, "unverified")

    def _email(self, d: dict[str, Any]) -> ControlOutcome:
        try:
            if not d["outlook"]:
                self.mailer.open_mailto(d["email"], d["subject"], d["text"])
                return ControlOutcome(f"Email ka draft ({d['to']}) default mail app mein khol diya — Outlook is PC par set "
                                      "nahi, is liye Send aap khud dabayein.", "email_draft", True, "unverified")
            if d["draft"]:
                ok = self.mailer.draft_outlook(d["email"], d["subject"], d["text"], d["attachments"])
                return ControlOutcome(f"Outlook mein {d['to']} ke liye draft bana diya (Drafts mein bhi hai) — bheja nahi."
                                      + (" (Verify: draft save hua.)" if ok else ""), "email_draft", True,
                                      "passed" if ok else "unverified")
            status = self.mailer.send_outlook(d["email"], d["subject"], d["text"], d["attachments"])
        except (MailError, OSError) as exc:
            return ControlOutcome(f"Email nahi bhej saka: {exc}.", "email_send", False, "failed")
        if status == "sent":
            return ControlOutcome(f"Outlook se {d['to']} ko email bhej di. (Verify: Sent Items mein hai.)", "email_send",
                                  True, "passed")
        if status == "outbox":
            return ControlOutcome(f"Email {d['to']} ke liye Outbox mein hai — abhi gayi nahi (internet/Outlook check "
                                  "karein).", "email_send", True, "failed")
        return ControlOutcome("Outlook ko email de di, lekin Sent Items mein nazar nahi aayi — Outlook mein check kar lein.",
                              "email_send", True, "unverified")
