"""What a File/Coding step will do, worked out *before* the user is asked - and then executed exactly.

Resolving paths, plans and code changes up front means the permission dialog shows the real target (the
file that will be deleted, the diff that will be written), and nothing different can run after "haan".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Prepared:
    summary: str  # one line for the permission question, e.g. "\"notes.txt\" -> \"final.txt\" (Desktop)"
    scope_key: str  # what a remembered approval would cover, e.g. "rename@C:\\Users\\me\\Desktop"
    preview: str | None = None  # shown in the dialog: a diff, an organize plan, the exact command
    count: int = 0  # files affected
    size: int = 0  # bytes affected
    executes_code: bool = False  # the project's own code/scripts will run
    network: bool = False  # packages will be downloaded
    always_ask: bool = False  # never covered by a remembered approval
    min_risk: str = "low"  # the agent's own judgement of the resolved action (the engine may raise it further)
    reasons: list[str] = field(default_factory=list)  # why it is risky, shown in the dialog
    data: dict[str, Any] = field(default_factory=dict)  # agent-specific: resolved paths, plan, proposal...


@dataclass
class Reply:
    """No action: a question back ("kaun si file?"), "not found", or a refusal NOVA makes itself."""

    message: str
    refused: bool = False
