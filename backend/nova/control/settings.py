"""Windows settings the System Agent may change (admin's choice for Phase 8C): volume/mute, brightness,
dark/light mode, Wi-Fi and Bluetooth. Every change is read back afterwards. Anything else opens the
right Windows Settings page so the user changes it there. Security settings (Defender, firewall, UAC,
BitLocker...) are never changed by NOVA.
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import re
import subprocess
import sys
import winreg
from typing import Literal

CREATE_NO_WINDOW = 0x08000000
PERSONALIZE = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
Radio = Literal["wifi", "bluetooth"]

# Settings pages NOVA can open (ms-settings: links). Keys are what the agent resolves user words to.
SETTINGS_PAGES: dict[str, tuple[str, str]] = {
    "home": ("ms-settings:", "Settings"),
    "default_apps": ("ms-settings:defaultapps", "Default apps"),
    "display": ("ms-settings:display", "Display"),
    "sound": ("ms-settings:sound", "Sound"),
    "bluetooth": ("ms-settings:bluetooth", "Bluetooth & devices"),
    "wifi": ("ms-settings:network-wifi", "Wi-Fi"),
    "network": ("ms-settings:network", "Network & internet"),
    "update": ("ms-settings:windowsupdate", "Windows Update"),
    "night_light": ("ms-settings:nightlight", "Night light"),
    "colors": ("ms-settings:colors", "Colors"),
    "background": ("ms-settings:personalization-background", "Background (wallpaper)"),
    "notifications": ("ms-settings:notifications", "Notifications"),
    "focus": ("ms-settings:quiethours", "Focus"),
    "power": ("ms-settings:powersleep", "Power & sleep"),
    "battery": ("ms-settings:batterysaver", "Battery"),
    "storage": ("ms-settings:storagesense", "Storage"),
    "apps": ("ms-settings:appsfeatures", "Installed apps"),
    "startup": ("ms-settings:startupapps", "Startup apps"),
    "mouse": ("ms-settings:mousetouchpad", "Mouse & touchpad"),
    "keyboard": ("ms-settings:typing", "Typing"),
    "language": ("ms-settings:regionlanguage", "Language & region"),
    "date_time": ("ms-settings:dateandtime", "Date & time"),
    "privacy": ("ms-settings:privacy", "Privacy & security"),
    "microphone": ("ms-settings:privacy-microphone", "Microphone privacy"),
    "camera": ("ms-settings:privacy-webcam", "Camera privacy"),
    "accounts": ("ms-settings:yourinfo", "Accounts"),
    "printers": ("ms-settings:printers", "Printers & scanners"),
    "about": ("ms-settings:about", "About"),
    "security": ("windowsdefender:", "Windows Security"),  # opened only; never changed by NOVA
}


class SettingsError(Exception):
    """A setting could not be read or changed; message is Roman Urdu."""


class WindowsSettings:
    """The real machine. Tests substitute a fake with the same methods."""

    # ------------------------------------------------------------------ volume (Core Audio)

    @staticmethod
    def _endpoint():
        import comtypes
        from pycaw.pycaw import AudioUtilities

        comtypes.CoInitialize()  # worker threads need their own COM apartment
        device = AudioUtilities.GetSpeakers()
        if device is None:
            raise SettingsError("Koi speaker/audio device nahi mila")
        return device.EndpointVolume

    def volume(self) -> int:
        return round(self._endpoint().GetMasterVolumeLevelScalar() * 100)

    def set_volume(self, percent: int) -> None:
        endpoint = self._endpoint()
        endpoint.SetMasterVolumeLevelScalar(max(0, min(100, percent)) / 100, None)
        if percent > 0 and endpoint.GetMute():
            endpoint.SetMute(0, None)  # "volume 50 karo" while muted should be audible

    def muted(self) -> bool:
        return bool(self._endpoint().GetMute())

    def set_mute(self, mute: bool) -> None:
        self._endpoint().SetMute(1 if mute else 0, None)

    # ------------------------------------------------------------------ brightness (WMI, built-in display)

    @staticmethod
    def _powershell(command: str) -> str:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True,
                           text=True, timeout=20, creationflags=CREATE_NO_WINDOW)
        if p.returncode != 0:
            raise SettingsError("Brightness sirf laptop ki apni screen par badli ja sakti hai (bahar wala monitor nahi)")
        return p.stdout.strip()

    def brightness(self) -> int | None:
        try:
            out = self._powershell("(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness "
                                   "-ErrorAction Stop | Select-Object -First 1).CurrentBrightness")
        except SettingsError:
            return None
        return int(out) if out.isdigit() else None

    def set_brightness(self, percent: int) -> None:
        value = max(0, min(100, int(percent)))
        self._powershell("Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop "
                         f"| Invoke-CimMethod -MethodName WmiSetBrightness -Arguments @{{Timeout=1; Brightness={value}}} "
                         "| Out-Null")

    # ------------------------------------------------------------------ dark / light mode (registry)

    def theme(self) -> str:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return "light" if value else "dark"

    def set_theme(self, theme: str) -> None:
        light = 1 if theme == "light" else 0
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, PERSONALIZE, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, light)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, light)
        # Tell open windows (taskbar, Explorer, apps) to repaint with the new colours.
        HWND_BROADCAST, WM_SETTINGCHANGE, SMTO_ABORTIFHUNG = 0xFFFF, 0x001A, 0x0002
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet",
                                                 SMTO_ABORTIFHUNG, 2000, ctypes.byref(result))

    # ------------------------------------------------------------------ Wi-Fi / Bluetooth (Windows.Devices.Radios)

    @staticmethod
    async def _radio(kind: Radio):
        from winrt.windows.devices.radios import Radio as WinRadio
        from winrt.windows.devices.radios import RadioAccessStatus, RadioKind

        if await WinRadio.request_access_async() != RadioAccessStatus.ALLOWED:
            raise SettingsError("Windows ne radio (Wi-Fi/Bluetooth) control ki ijazat nahi di")
        wanted = RadioKind.WI_FI if kind == "wifi" else RadioKind.BLUETOOTH
        radios = [r for r in await WinRadio.get_radios_async() if r.kind == wanted]
        if not radios:
            raise SettingsError(f"Is PC par {'Wi-Fi' if kind == 'wifi' else 'Bluetooth'} adapter nahi mila")
        return radios[0]

    def radio(self, kind: Radio) -> str:
        from winrt.windows.devices.radios import RadioState

        async def read() -> str:
            return "on" if (await self._radio(kind)).state == RadioState.ON else "off"

        return asyncio.run(read())

    def set_radio(self, kind: Radio, on: bool) -> None:
        from winrt.windows.devices.radios import RadioAccessStatus, RadioState

        async def change() -> None:
            radio = await self._radio(kind)
            status = await radio.set_state_async(RadioState.ON if on else RadioState.OFF)
            if status != RadioAccessStatus.ALLOWED:
                raise SettingsError("Windows ne ye badlaav nahi karne diya")

        asyncio.run(change())

    # ------------------------------------------------------------------ settings pages

    def open_page(self, uri: str) -> None:
        if not re.fullmatch(r"(?:ms-settings:[\w\-]*|windowsdefender:)", uri):
            raise SettingsError("Ye Settings page nahi")
        if sys.platform == "win32":
            os.startfile(uri)  # noqa: S606 - only fixed ms-settings: links from SETTINGS_PAGES
