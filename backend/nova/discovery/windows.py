"""Read-only Windows collectors. Each function returns plain data and may raise; the scanner
isolates failures so one broken source never blocks the rest of the profile."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import psutil

from .models import (
    AppEntry,
    AudioDevice,
    BrowserInfo,
    DriveInfo,
    GpuInfo,
    NetworkInterface,
    PermissionsInfo,
    RunningApp,
    ServiceInfo,
    StartupItem,
)

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    import winreg
    from ctypes import wintypes

PROBE_SCRIPT = Path(__file__).with_name("probe.ps1")
CREATE_NO_WINDOW = 0x08000000

# Services that matter for NOVA's capabilities (audio, search, updates, security). Read-only.
RELEVANT_SERVICES = ("Audiosrv", "AudioEndpointBuilder", "WSearch", "wuauserv", "WinDefend", "mpssvc", "Spooler")


def as_list(value: Any) -> list[Any]:
    """PowerShell's ConvertTo-Json collapses one-item arrays into objects."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


# --------------------------------------------------------------------------- PowerShell probe


def run_probe(timeout: int = 90) -> dict[str, Any]:
    """Run probe.ps1 via -EncodedCommand (execution policy applies only to script files)."""
    script = PROBE_SCRIPT.read_text(encoding="utf-8")
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        timeout=timeout,
        creationflags=CREATE_NO_WINDOW if IS_WINDOWS else 0,
    )
    out = proc.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        raise RuntimeError(f"probe produced no output (exit {proc.returncode})")
    return json.loads(out[out.index("{"):])


# --------------------------------------------------------------------------- registry helpers


def _reg_values(root: Any, path: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    try:
        with winreg.OpenKey(root, path) as key:
            i = 0
            while True:
                try:
                    name, value, _ = winreg.EnumValue(key, i)
                except OSError:
                    break
                values[name] = value
                i += 1
    except OSError:
        pass
    return values


def _reg_subkeys(root: Any, path: str) -> list[str]:
    names: list[str] = []
    try:
        with winreg.OpenKey(root, path) as key:
            i = 0
            while True:
                try:
                    names.append(winreg.EnumKey(key, i))
                except OSError:
                    break
                i += 1
    except OSError:
        pass
    return names


def _clean_exe(value: Any) -> str | None:
    """Turn '"C:\\x\\app.exe",0' or 'C:\\x\\app.exe --flag' into the exe path."""
    if not isinstance(value, str) or not value:
        return None
    m = re.match(r'\s*"([^"]+\.exe)"', value, re.IGNORECASE) or re.match(r"\s*(.+?\.exe)\b", value, re.IGNORECASE)
    return m.group(1) if m else None


# --------------------------------------------------------------------------- hardware


def gpu_from_probe(raw: list[dict[str, Any]]) -> list[GpuInfo]:
    registry_memory = _gpu_registry_memory() if IS_WINDOWS else {}
    gpus = []
    for g in raw:
        name = (g.get("Name") or "").strip()
        if not name:
            continue
        pnp = (g.get("PNPDeviceID") or "").upper()
        vendor = (
            "nvidia" if "VEN_10DE" in pnp or "NVIDIA" in name.upper()
            else "amd" if "VEN_1002" in pnp or "AMD" in name.upper() or "RADEON" in name.upper()
            else "intel" if "VEN_8086" in pnp or "INTEL" in name.upper()
            else "other"
        )
        # AdapterRAM is a 32-bit field (caps at 4 GB); the driver's registry value is exact.
        memory = registry_memory.get(name) or g.get("AdapterRAM") or None
        if vendor == "nvidia":
            dedicated: bool | None = True
        elif vendor == "intel":
            dedicated = "ARC" in name.upper()
        elif vendor == "amd":
            dedicated = bool(re.search(r"\bRX\b|RADEON PRO", name.upper()))
        else:
            dedicated = None
        gpus.append(GpuInfo(name=name, memory_bytes=memory, driver_version=g.get("DriverVersion"),
                            vendor=vendor, dedicated=dedicated))
    return gpus


def _gpu_registry_memory() -> dict[str, int]:
    base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
    result: dict[str, int] = {}
    for sub in _reg_subkeys(winreg.HKEY_LOCAL_MACHINE, base):
        if not sub.isdigit():
            continue
        values = _reg_values(winreg.HKEY_LOCAL_MACHINE, rf"{base}\{sub}")
        desc = values.get("DriverDesc")
        mem = values.get("HardwareInformation.qwMemorySize") or values.get("HardwareInformation.MemorySize")
        if isinstance(mem, bytes):
            mem = int.from_bytes(mem, "little")
        if isinstance(desc, str) and isinstance(mem, int) and mem > 0:
            result[desc.strip()] = mem
    return result


def drives() -> list[DriveInfo]:
    result = []
    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts or not part.fstype:
            continue
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        result.append(DriveInfo(mountpoint=part.mountpoint, filesystem=part.fstype,
                                total_bytes=usage.total, free_bytes=usage.free))
    return result


def network() -> tuple[list[NetworkInterface], bool]:
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    interfaces = []
    connected = False
    for name, st in stats.items():
        if "loopback" in name.lower():
            continue
        ipv4 = [a.address for a in addrs.get(name, []) if a.family.name == "AF_INET"]
        usable = [ip for ip in ipv4 if not ip.startswith(("127.", "169.254."))]
        if st.isup and usable:
            connected = True
        interfaces.append(NetworkInterface(name=name, is_up=st.isup, ipv4=ipv4))
    return interfaces, connected


# --------------------------------------------------------------------------- audio devices

_PKEY_DEVICE_DESC = "{a45c254e-df1c-4efd-8020-67d146a850e0},2"
_PKEY_INTERFACE_NAME = "{b3f8fa53-0004-438e-9003-51a46e139bfc},6"
_DEVICE_STATE_ACTIVE = 1


def audio_devices() -> tuple[list[AudioDevice], list[AudioDevice]]:
    """Active capture (microphone) and render (speaker) endpoints from the MMDevices registry."""
    base = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio"
    found: dict[str, list[AudioDevice]] = {"Capture": [], "Render": []}
    for flow, kind in (("Capture", "input"), ("Render", "output")):
        for guid in _reg_subkeys(winreg.HKEY_LOCAL_MACHINE, rf"{base}\{flow}"):
            state = _reg_values(winreg.HKEY_LOCAL_MACHINE, rf"{base}\{flow}\{guid}").get("DeviceState")
            if state != _DEVICE_STATE_ACTIVE:
                continue
            props = _reg_values(winreg.HKEY_LOCAL_MACHINE, rf"{base}\{flow}\{guid}\Properties")
            desc, iface = props.get(_PKEY_DEVICE_DESC), props.get(_PKEY_INTERFACE_NAME)
            if not desc:
                continue
            name = f"{desc} ({iface})" if iface else str(desc)
            found[flow].append(AudioDevice(name=name, kind=kind))
    return found["Capture"], found["Render"]


# --------------------------------------------------------------------------- applications


def registry_apps() -> list[AppEntry]:
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    apps = []
    for root, path in roots:
        for sub in _reg_subkeys(root, path):
            v = _reg_values(root, rf"{path}\{sub}")
            name = v.get("DisplayName")
            if not isinstance(name, str) or not name.strip():
                continue
            if v.get("SystemComponent") == 1 or v.get("ParentKeyName") or v.get("ReleaseType") in (
                "Update", "Hotfix", "Security Update",
            ):
                continue
            apps.append(
                AppEntry(
                    name=name.strip(),
                    version=v.get("DisplayVersion") if isinstance(v.get("DisplayVersion"), str) else None,
                    publisher=v.get("Publisher") if isinstance(v.get("Publisher"), str) else None,
                    sources=["registry"],
                    executable=_clean_exe(v.get("DisplayIcon")),
                    install_location=v.get("InstallLocation") or None,
                )
            )
    return apps


def app_paths() -> dict[str, str]:
    """exe name (lowercase) -> full path, from the App Paths registry used by the Run dialog."""
    result: dict[str, str] = {}
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        for sub in _reg_subkeys(root, path):
            exe = _clean_exe(_reg_values(root, rf"{path}\{sub}").get(""))
            if exe and sub.lower().endswith(".exe"):
                result.setdefault(sub.lower(), os.path.expandvars(exe))
    return result


_PROGID_BROWSERS = {
    "chromehtml": "Google Chrome",
    "msedgehtm": "Microsoft Edge",
    "firefoxurl": "Firefox",
    "bravehtml": "Brave",
    "operastable": "Opera",
    "operagxstable": "Opera GX",
    "vivaldihtm": "Vivaldi",
}


def browsers() -> list[BrowserInfo]:
    found: dict[str, BrowserInfo] = {}
    for root, path in (
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Clients\StartMenuInternet"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Clients\StartMenuInternet"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Clients\StartMenuInternet"),
    ):
        for sub in _reg_subkeys(root, path):
            name = _reg_values(root, rf"{path}\{sub}").get("") or sub
            exe = _clean_exe(_reg_values(root, rf"{path}\{sub}\shell\open\command").get(""))
            key = str(name).lower()
            if key not in found:
                found[key] = BrowserInfo(name=str(name), executable=exe)

    default = _default_browser_name()
    if default:
        for b in found.values():
            if default.lower() in b.name.lower() or b.name.lower() in default.lower():
                b.is_default = True
                break
    return sorted(found.values(), key=lambda b: (not b.is_default, b.name.lower()))


def _default_browser_name() -> str | None:
    base = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https"
    prog_id = None
    # Windows 11 24H2+ writes UserChoiceLatest; older builds use UserChoice.
    for sub in ("UserChoiceLatest", "UserChoice"):
        prog_id = _reg_values(winreg.HKEY_CURRENT_USER, rf"{base}\{sub}").get("ProgId")
        if prog_id:
            break
    if not prog_id:
        return None
    for prefix, name in _PROGID_BROWSERS.items():
        if prog_id.lower().startswith(prefix):
            return name
    app_name = _reg_values(winreg.HKEY_CLASSES_ROOT, rf"{prog_id}\Application").get("ApplicationName")
    return app_name if isinstance(app_name, str) else prog_id


def running_apps() -> list[RunningApp]:
    """Processes that own a visible, titled top-level window (what the user sees as 'open apps')."""
    user32 = ctypes.windll.user32
    GW_OWNER = 4
    GWL_EXSTYLE = -20
    WS_EX_TOOLWINDOW = 0x00000080
    windows: dict[int, str] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
            return True
        if user32.GetWindowLongW(hwnd, GWL_EXSTYLE) & WS_EX_TOOLWINDOW:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        windows.setdefault(pid.value, buf.value)
        return True

    user32.EnumWindows(callback, 0)
    result = []
    for pid, title in windows.items():
        try:
            name = psutil.Process(pid).name()
        except (psutil.Error, OSError):
            continue
        result.append(RunningApp(name=name, title=title, pid=pid))
    return sorted(result, key=lambda r: r.name.lower())


def startup_items() -> list[StartupItem]:
    items = []
    run_keys = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKLM Run (32-bit)"),
    ]
    for root, path, label in run_keys:
        for name, command in _reg_values(root, path).items():
            if name:
                items.append(StartupItem(name=name, location=label, command=str(command)))
    folders = [
        (os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"), "Startup folder (user)"),
        (os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs\StartUp"), "Startup folder (all users)"),
    ]
    for folder, label in folders:
        p = Path(folder)
        if p.is_dir():
            for f in p.iterdir():
                if f.suffix.lower() in (".lnk", ".exe", ".bat", ".cmd", ".url"):
                    items.append(StartupItem(name=f.stem, location=label, command=str(f)))
    return items


def services() -> list[ServiceInfo]:
    result = []
    for name in RELEVANT_SERVICES:
        try:
            s = psutil.win_service_get(name).as_dict()
        except (psutil.Error, OSError):
            continue
        result.append(ServiceInfo(name=name, display_name=s.get("display_name"),
                                  status=s.get("status"), start_type=s.get("start_type")))
    return result


def permissions() -> PermissionsInfo:
    elevated = bool(ctypes.windll.shell32.IsUserAnAdmin())
    in_admin_group = elevated
    if not elevated:
        # A non-elevated admin still lists S-1-5-32-544 (as "deny only") in its token groups.
        try:
            out = subprocess.run(["whoami", "/groups", "/fo", "csv"], capture_output=True, timeout=10,
                                 creationflags=CREATE_NO_WINDOW).stdout.decode("utf-8", errors="replace")
            in_admin_group = "S-1-5-32-544" in out
        except (OSError, subprocess.SubprocessError):
            pass
    return PermissionsInfo(is_elevated=elevated, user_is_admin=in_admin_group)
