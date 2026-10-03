"""Which networks this PC is on, and whether Windows calls each one Private or Public.

Multi-PC only listens on Private (home/office) or domain networks. On a Public network (cafe, hotel) it stays off;
switching a network to Private is the user's own choice in Windows Settings - NOVA never changes it.
"""

from __future__ import annotations

import ipaddress
import json
import subprocess
from dataclasses import dataclass

CREATE_NO_WINDOW = 0x08000000
PRIVATE_CATEGORIES = ("Private", "DomainAuthenticated")

# One IPv4 address per connected network, with the network's Windows category (Public / Private / DomainAuthenticated).
_SCRIPT = (
    "$p = @{}; Get-NetConnectionProfile | ForEach-Object { $p[[int]$_.InterfaceIndex] = @{c = [string]$_.NetworkCategory;"
    " n = [string]$_.Name} }; @(Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object "
    "{ $p.ContainsKey([int]$_.InterfaceIndex) } | ForEach-Object { [pscustomobject]@{ip = $_.IPAddress; prefix = "
    "[int]$_.PrefixLength; alias = [string]$_.InterfaceAlias; category = $p[[int]$_.InterfaceIndex].c; name = "
    "$p[[int]$_.InterfaceIndex].n} }) | ConvertTo-Json -Compress"
)


@dataclass(frozen=True)
class NetInfo:
    ip: str
    prefix: int
    alias: str  # adapter, e.g. "Wi-Fi"
    category: str  # Public | Private | DomainAuthenticated
    name: str  # network name, e.g. the Wi-Fi name

    @property
    def private(self) -> bool:
        return self.category in PRIVATE_CATEGORIES

    @property
    def subnet(self) -> ipaddress.IPv4Network:
        return ipaddress.IPv4Network(f"{self.ip}/{self.prefix}", strict=False)

    @property
    def broadcast(self) -> str:
        return str(self.subnet.broadcast_address)

    def contains(self, ip: str) -> bool:
        try:
            return ipaddress.IPv4Address(ip) in self.subnet
        except ValueError:
            return False

    def to_dict(self) -> dict[str, object]:
        return {"ip": self.ip, "alias": self.alias, "category": self.category, "name": self.name,
                "private": self.private}


LOOPBACK = NetInfo("127.0.0.1", 8, "Loopback", "Private", "is PC ke andar (test)")


def list_networks() -> list[NetInfo]:
    """The connected IPv4 networks (Windows PowerShell, ~1 s). Empty when nothing is connected or the call fails."""
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _SCRIPT], capture_output=True,
                             text=True, timeout=20, creationflags=CREATE_NO_WINDOW).stdout.strip()
        rows = json.loads(out) if out else []
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    if isinstance(rows, dict):
        rows = [rows]
    nets = []
    for row in rows if isinstance(rows, list) else []:
        try:
            ip = str(ipaddress.IPv4Address(str(row.get("ip"))))
            prefix = int(row.get("prefix"))
        except (ValueError, TypeError):
            continue
        if ip.startswith(("169.254.", "127.")) or not 0 < prefix <= 32:
            continue  # link-local "no DHCP" address, loopback
        nets.append(NetInfo(ip, prefix, str(row.get("alias") or "")[:60], str(row.get("category") or "Public"),
                            str(row.get("name") or "")[:80]))
    return nets
