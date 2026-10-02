"""Discovery service: runs scans off the event loop, persists the profile, applies safe settings."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from ..db import Database
from ..events import EventBus, EventType, NovaEvent
from .models import LiveStats, SystemProfile
from .scanner import live_stats, scan

log = logging.getLogger("nova.discovery")

SYSTEM_AGENT = "System Agent"


class DiscoveryService:
    def __init__(
        self,
        db: Database,
        bus: EventBus,
        scanner: Callable[[], SystemProfile] = scan,
        stats: Callable[[], LiveStats] = live_stats,
    ) -> None:
        self.db = db
        self.bus = bus
        self._scanner = scanner
        self._stats = stats
        self._lock = asyncio.Lock()
        self._profile: SystemProfile | None = None
        stored = db.latest_system_profile()
        if stored:
            try:
                self._profile = SystemProfile.model_validate_json(stored)
            except ValueError:
                log.warning("Stored system profile is unreadable; a new scan will replace it")

    @property
    def profile(self) -> SystemProfile | None:
        return self._profile

    @property
    def scanning(self) -> bool:
        return self._lock.locked()

    async def run_scan(self, reason: str = "manual") -> SystemProfile:
        async with self._lock:
            await self.bus.publish(
                NovaEvent(type=EventType.DISCOVERY_STARTED, agent=SYSTEM_AGENT,
                          message="System scan shuru", data={"reason": reason})
            )
            try:
                profile = await asyncio.to_thread(self._scanner)
            except Exception as exc:
                log.exception("System discovery failed")
                await self.bus.publish(
                    NovaEvent(type=EventType.DISCOVERY_FAILED, agent=SYSTEM_AGENT,
                              message="System scan nakam raha", data={"error": type(exc).__name__})
                )
                self.db.add_activity(task_id="discovery", task_name="system_discovery", agent=SYSTEM_AGENT,
                                     action="scan", execution_status="failed", error=f"{type(exc).__name__}: {exc}",
                                     final_result="failed")
                raise

            self.db.save_system_profile(profile.model_dump_json())
            for rec in profile.recommendations:
                if rec.auto_applied:
                    self.db.set_setting(rec.key, rec.value)
            self._profile = profile

            # Verification: re-read what was persisted and confirm it round-trips.
            stored = self.db.latest_system_profile()
            verified = stored is not None and SystemProfile.model_validate_json(stored).scanned_at == profile.scanned_at
            self.db.add_activity(
                task_id="discovery", task_name="system_discovery", agent=SYSTEM_AGENT, action="scan",
                execution_status="success", test_status="passed" if verified else "failed",
                verification_status="passed" if verified else "failed",
                error="; ".join(profile.errors) or None,
                final_result=f"{len(profile.apps)} apps, {len(profile.errors)} collector errors",
            )
            await self.bus.publish(
                NovaEvent(
                    type=EventType.DISCOVERY_COMPLETED,
                    agent=SYSTEM_AGENT,
                    message=f"System scan mukammal — {len(profile.apps)} applications mili ({profile.scan_duration_ms / 1000:.1f}s)",
                    data={"apps": len(profile.apps), "errors": len(profile.errors), "verified": verified},
                )
            )
            return profile

    async def live(self) -> LiveStats:
        return await asyncio.to_thread(self._stats)
