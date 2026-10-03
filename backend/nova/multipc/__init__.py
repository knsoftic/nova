"""Multi-PC (Phase 13): PC identity, finding NOVA on the local network, pairing, encrypted PC-to-PC requests."""

from .agent import MULTIPC_INTENTS, MultiPcAgent
from .link import LinkError
from .service import NAME, MultiPcService

__all__ = ["MULTIPC_INTENTS", "NAME", "LinkError", "MultiPcAgent", "MultiPcService"]
