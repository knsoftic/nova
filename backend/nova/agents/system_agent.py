"""System Agent (read-only in Phase 2): answers questions from the system profile and live stats.

All text returned here is user-facing Roman Urdu.
"""

from __future__ import annotations

from ..discovery.apps import find_app
from ..discovery.models import LiveStats, SystemProfile

NAME = "System Agent"
GB = 1024**3


def gb(n: int | None) -> str:
    if not n:
        return "?"
    value = n / GB
    return f"{value:.1f} GB" if value < 10 else f"{value:.0f} GB"


def pc_name(p: SystemProfile) -> str:
    maker, model = p.windows.manufacturer or "", p.windows.model or ""
    # Many OEMs repeat the brand in the model string ("HP" + "HP EliteBook 845 G8").
    if maker and model.lower().startswith(maker.lower()):
        return model
    return " ".join(x for x in (maker, model) if x)


def _cpu(p: SystemProfile, live: LiveStats | None) -> str:
    c = p.cpu
    text = f"Processor: {c.name or 'detect nahi hua'}"
    if c.cores and c.threads:
        text += f" ({c.cores} cores / {c.threads} threads)"
    if live:
        text += f". Is waqt CPU usage {live.cpu_percent:.0f}% hai"
    return text + "."


def _ram(p: SystemProfile, live: LiveStats | None) -> str:
    if live:
        return (f"RAM: total {gb(live.ram_total_bytes)}, is waqt {gb(live.ram_available_bytes)} free hai "
                f"({live.ram_percent:.0f}% use ho rahi hai).")
    return f"RAM: total {gb(p.ram_total_bytes)}."


def _gpu(p: SystemProfile) -> str:
    if not p.gpus:
        return "GPU detect nahi hua."
    parts = []
    for g in p.gpus:
        kind = "dedicated" if g.dedicated else "integrated" if g.dedicated is False else "type maloom nahi"
        mem = f", {gb(g.memory_bytes)} memory" if g.memory_bytes else ""
        parts.append(f"{g.name} ({kind}{mem})")
    return "GPU: " + "; ".join(parts) + "."


def _storage(p: SystemProfile, live: LiveStats | None) -> str:
    drives = live.drives if live else p.drives
    if not drives:
        return "Storage detect nahi hui."
    parts = [f"{d.mountpoint.rstrip(chr(92))} {gb(d.free_bytes)} free / {gb(d.total_bytes)}" for d in drives]
    return "Storage: " + ", ".join(parts) + "."


def _windows(p: SystemProfile) -> str:
    w = p.windows
    text = f"Windows: {w.caption or 'Windows'}"
    if w.display_version:
        text += f" {w.display_version}"
    if w.build:
        text += f" (build {w.build})"
    if w.architecture:
        text += f", {w.architecture}"
    return text + "."


def _devices(p: SystemProfile) -> str:
    mic = p.microphones[0].name if p.microphones else "nahi mila"
    spk = p.speakers[0].name if p.speakers else "nahi mila"
    cam = ", ".join(p.cameras) if p.cameras else "nahi mila"
    return f"Microphone: {mic}. Speaker: {spk}. Camera: {cam}."


def _displays(p: SystemProfile) -> str:
    if not p.displays:
        return "Display detect nahi hua."
    parts = [f"{d.width}x{d.height}{' (primary)' if d.primary else ''}" for d in p.displays]
    return f"{len(p.displays)} display: " + ", ".join(parts) + "."


def _network(p: SystemProfile) -> str:
    up = [n.name for n in p.network if n.is_up and any(not ip.startswith(("127.", "169.254.")) for ip in n.ipv4)]
    if p.network_connected:
        return f"Network connected hai ({', '.join(up)})."
    return "Network connected nahi hai."


def _admin(p: SystemProfile) -> str:
    perm = p.permissions
    if perm.is_elevated:
        return "NOVA is waqt administrator rights ke sath chal raha hai."
    if perm.user_is_admin:
        return "Aapka account administrator hai, lekin NOVA normal (non-elevated) mode mein chal raha hai."
    return "Aapka account standard user hai; administrator rights available nahi."


def _browsers(p: SystemProfile) -> str:
    if not p.browsers:
        return "Koi browser detect nahi hua."
    default = next((b.name for b in p.browsers if b.is_default), None)
    names = ", ".join(b.name for b in p.browsers)
    return f"Browsers: {names}." + (f" Default browser: {default}." if default else " Default browser maloom nahi hua.")


def _apps(p: SystemProfile) -> str:
    known = ["Google Chrome", "Visual Studio Code", "WhatsApp", "Adobe Photoshop", "Microsoft Edge", "Firefox"]
    found = [m.app.name for k in known if (m := find_app(p.apps, k)) and m.score >= 0.9]
    text = f"Is PC par {len(p.apps)} applications detect hui hain."
    if found:
        text += " Aham: " + ", ".join(found) + "."
    return text


def _running(p: SystemProfile) -> str:
    if not p.running_apps:
        return "Is waqt koi khuli window detect nahi hui."
    names = sorted({r.name.removesuffix(".exe") for r in p.running_apps})
    return f"Scan ke waqt khuli applications: {', '.join(names)}."


def describe(topic: str, p: SystemProfile, live: LiveStats | None) -> str:
    match topic:
        case "cpu":
            return _cpu(p, live)
        case "ram":
            return _ram(p, live)
        case "gpu":
            return _gpu(p)
        case "storage":
            return _storage(p, live)
        case "windows":
            return _windows(p)
        case "devices":
            return _devices(p)
        case "displays":
            return _displays(p)
        case "network":
            return _network(p)
        case "admin":
            return _admin(p)
        case "browsers":
            return _browsers(p)
        case "apps":
            return _apps(p)
        case "running":
            return _running(p)
    model = pc_name(p)
    lines = [
        f"Aapke system ({model or p.windows.computer_name or 'PC'}) ki report:",
        _cpu(p, live),
        _ram(p, live),
        _gpu(p),
        _storage(p, live),
        _windows(p),
        _devices(p),
        _apps(p),
        _admin(p),
    ]
    if p.errors:
        lines.append(f"Note: {len(p.errors)} cheezein detect nahi ho sakin (detail System Profile mein).")
    return "\n".join(lines)


def describe_app(query: str, p: SystemProfile) -> tuple[str, bool]:
    """Returns (response, found)."""
    match = find_app(p.apps, query)
    if not match:
        return f"Mujhe is PC par \"{query}\" naam ki koi application nahi mili.", False
    app = match.app
    extra = f" (version {app.version})" if app.version else ""
    return f"Haan, {app.name}{extra} is PC par installed hai.", True


def describe_open_app(query: str, p: SystemProfile | None, launch_phase: int) -> str:
    if p is None:
        return (f"Main samajh gaya, aap {query} open karwana chahte hain. System scan abhi mukammal nahi hua. "
                f"Application launch Phase {launch_phase} mein aayega, is liye abhi koi action nahi kiya gaya.")
    match = find_app(p.apps, query)
    if not match:
        return f"Mujhe is PC par \"{query}\" nahi mila, is liye open nahi kar sakta. Kya naam sahi hai?"
    return (f"{match.app.name} is PC par installed hai. Application launch ki capability Phase {launch_phase} "
            "mein aayegi, is liye abhi koi action nahi kiya gaya.")
