"""Builds a SystemProfile from all collectors. Each collector is isolated: a failure is recorded
in profile.errors instead of aborting the scan."""

from __future__ import annotations

import logging
import platform
import sys
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

import psutil

from . import windows as win
from .apps import merge_apps
from .models import CpuInfo, DisplayInfo, LiveStats, PhysicalDisk, SystemProfile, WindowsInfo
from .recommend import recommend

log = logging.getLogger("nova.discovery")
T = TypeVar("T")


def _safe(errors: list[str], label: str, fn: Callable[[], T], default: T) -> T:
    try:
        return fn()
    except Exception as exc:  # collectors touch the OS; never let one break the profile
        log.warning("Discovery collector %s failed: %s", label, exc)
        errors.append(f"{label}: {type(exc).__name__}: {exc}")
        return default


def scan() -> SystemProfile:
    started = time.perf_counter()
    errors: list[str] = []
    profile = SystemProfile(
        scanned_at=datetime.now(timezone.utc).isoformat(),
        scan_duration_ms=0,
        platform=sys.platform,
    )
    profile.ram_total_bytes = psutil.virtual_memory().total
    profile.drives = _safe(errors, "drives", win.drives, [])
    profile.network, profile.network_connected = _safe(errors, "network", win.network, ([], False))

    if not win.IS_WINDOWS:
        profile.cpu = CpuInfo(name=platform.processor() or None, cores=psutil.cpu_count(logical=False),
                              threads=psutil.cpu_count())
        profile.errors = ["Full discovery is only implemented for Windows."]
        profile.recommendations = recommend(profile)
        profile.scan_duration_ms = int((time.perf_counter() - started) * 1000)
        return profile

    probe: dict[str, Any] = _safe(errors, "powershell_probe", win.run_probe, {})

    cpus = win.as_list(probe.get("cpu"))
    if cpus:
        c = cpus[0]
        profile.cpu = CpuInfo(
            name=(c.get("Name") or "").strip() or None,
            manufacturer=c.get("Manufacturer"),
            cores=sum(int(x.get("NumberOfCores") or 0) for x in cpus) or None,
            threads=sum(int(x.get("NumberOfLogicalProcessors") or 0) for x in cpus) or None,
            max_clock_mhz=c.get("MaxClockSpeed"),
        )
    else:
        profile.cpu = CpuInfo(cores=psutil.cpu_count(logical=False), threads=psutil.cpu_count())

    os_info = probe.get("os") or {}
    computer = probe.get("computer") or {}
    profile.windows = WindowsInfo(
        caption=os_info.get("Caption"),
        version=os_info.get("Version") or platform.version(),
        build=os_info.get("BuildNumber"),
        display_version=probe.get("display_version"),
        architecture=os_info.get("OSArchitecture"),
        computer_name=platform.node() or None,
        manufacturer=computer.get("Manufacturer"),
        model=computer.get("Model"),
    )
    profile.gpus = _safe(errors, "gpu", lambda: win.gpu_from_probe(win.as_list(probe.get("gpu"))), [])
    profile.physical_disks = [
        PhysicalDisk(model=d.get("Model"), size_bytes=d.get("Size"), media_type=d.get("MediaType"),
                     interface=d.get("InterfaceType"))
        for d in win.as_list(probe.get("disks"))
    ]
    profile.cameras = [c["FriendlyName"] for c in win.as_list(probe.get("cameras")) if c.get("FriendlyName")]
    profile.displays = [
        DisplayInfo(name=d.get("name", "").lstrip("\\."), primary=bool(d.get("primary")),
                    width=d.get("width"), height=d.get("height"))
        for d in win.as_list(probe.get("displays"))
    ]
    profile.microphones, profile.speakers = _safe(errors, "audio", win.audio_devices, ([], []))

    registry = _safe(errors, "registry_apps", win.registry_apps, [])
    exe_paths = _safe(errors, "app_paths", win.app_paths, {})
    profile.apps = merge_apps(win.as_list(probe.get("start_apps")), registry, exe_paths)
    profile.browsers = _safe(errors, "browsers", win.browsers, [])
    profile.running_apps = _safe(errors, "running_apps", win.running_apps, [])
    profile.startup_items = _safe(errors, "startup_items", win.startup_items, [])
    profile.services = _safe(errors, "services", win.services, [])
    profile.permissions = _safe(errors, "permissions", win.permissions, profile.permissions)

    profile.recommendations = recommend(profile)
    profile.errors = errors
    profile.scan_duration_ms = int((time.perf_counter() - started) * 1000)
    return profile


def live_stats() -> LiveStats:
    vm = psutil.virtual_memory()
    return LiveStats(
        cpu_percent=psutil.cpu_percent(interval=0.3),
        ram_total_bytes=vm.total,
        ram_available_bytes=vm.available,
        ram_percent=vm.percent,
        drives=win.drives(),
        uptime_seconds=int(time.time() - psutil.boot_time()),
    )
