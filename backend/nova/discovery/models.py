"""System profile data model. Every field is optional because detection can fail per item."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CpuInfo(BaseModel):
    name: str | None = None
    manufacturer: str | None = None
    cores: int | None = None
    threads: int | None = None
    max_clock_mhz: int | None = None


class GpuInfo(BaseModel):
    name: str
    memory_bytes: int | None = None
    driver_version: str | None = None
    vendor: str | None = None  # nvidia | amd | intel | other
    dedicated: bool | None = None  # False for integrated/shared-memory GPUs


class DriveInfo(BaseModel):
    mountpoint: str
    filesystem: str | None = None
    total_bytes: int
    free_bytes: int


class PhysicalDisk(BaseModel):
    model: str | None = None
    size_bytes: int | None = None
    media_type: str | None = None
    interface: str | None = None


class WindowsInfo(BaseModel):
    caption: str | None = None
    version: str | None = None
    build: str | None = None
    display_version: str | None = None  # e.g. 25H2
    architecture: str | None = None
    computer_name: str | None = None
    manufacturer: str | None = None
    model: str | None = None


class AudioDevice(BaseModel):
    name: str
    kind: str  # input | output
    is_default: bool = False


class DisplayInfo(BaseModel):
    name: str
    primary: bool = False
    width: int | None = None
    height: int | None = None


class NetworkInterface(BaseModel):
    name: str
    is_up: bool
    ipv4: list[str] = Field(default_factory=list)


class AppEntry(BaseModel):
    name: str
    version: str | None = None
    publisher: str | None = None
    sources: list[str] = Field(default_factory=list)  # start_menu | registry | app_paths
    app_id: str | None = None  # Start menu AppUserModelID (works for Store apps too)
    executable: str | None = None
    install_location: str | None = None


class BrowserInfo(BaseModel):
    name: str
    executable: str | None = None
    is_default: bool = False


class RunningApp(BaseModel):
    name: str  # process image name
    title: str | None = None
    pid: int


class ServiceInfo(BaseModel):
    name: str
    display_name: str | None = None
    status: str | None = None
    start_type: str | None = None


class StartupItem(BaseModel):
    name: str
    location: str
    command: str | None = None


class PermissionsInfo(BaseModel):
    is_elevated: bool = False  # NOVA process currently runs as administrator
    user_is_admin: bool = False  # user account belongs to Administrators group


class Recommendation(BaseModel):
    key: str
    value: str
    reason: str  # user-facing, Roman Urdu
    auto_applied: bool = False  # True = written to settings; False = suggestion only (nothing installed)


class SystemProfile(BaseModel):
    scanned_at: str
    scan_duration_ms: int
    platform: str
    cpu: CpuInfo = Field(default_factory=CpuInfo)
    ram_total_bytes: int | None = None
    gpus: list[GpuInfo] = Field(default_factory=list)
    drives: list[DriveInfo] = Field(default_factory=list)
    physical_disks: list[PhysicalDisk] = Field(default_factory=list)
    windows: WindowsInfo = Field(default_factory=WindowsInfo)
    microphones: list[AudioDevice] = Field(default_factory=list)
    speakers: list[AudioDevice] = Field(default_factory=list)
    cameras: list[str] = Field(default_factory=list)
    displays: list[DisplayInfo] = Field(default_factory=list)
    network: list[NetworkInterface] = Field(default_factory=list)
    network_connected: bool = False
    apps: list[AppEntry] = Field(default_factory=list)
    browsers: list[BrowserInfo] = Field(default_factory=list)
    running_apps: list[RunningApp] = Field(default_factory=list)
    startup_items: list[StartupItem] = Field(default_factory=list)
    services: list[ServiceInfo] = Field(default_factory=list)
    permissions: PermissionsInfo = Field(default_factory=PermissionsInfo)
    recommendations: list[Recommendation] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)  # collectors that failed, for honest reporting


class LiveStats(BaseModel):
    cpu_percent: float
    ram_total_bytes: int
    ram_available_bytes: int
    ram_percent: float
    drives: list[DriveInfo]
    uptime_seconds: int
