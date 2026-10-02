"""Communication Agent: WhatsApp (click-to-chat) and email (Outlook / mail app), contacts saved by the user."""

from .agent import COMM_INTENTS, CommunicationAgent
from .email import Mailer
from .whatsapp import WhatsAppDesktop

__all__ = ["COMM_INTENTS", "CommunicationAgent", "Mailer", "WhatsAppDesktop"]
